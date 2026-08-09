# tests/test_streaming_pipeline.py — Déclenchement du pipeline de streaming
#
# Le graphe agent (LLM) est entièrement remplacé par un faux graphe : ces
# tests vérifient la DÉCISION de déclenchement (AnomalyDetector -> lance ou
# non une analyse) et les deux modes d'approbation, pas le contenu réel
# d'une analyse (couvert par tests/test_nodes_pipeline.py).
from pathlib import Path

import pytest

import agent.graph
from agent.state import AnalysisStatus
from agent.streaming.pipeline import StreamingAnalysisPipeline


class FakeSnapshot:
    def __init__(self, next_nodes, values):
        self.next = next_nodes
        self.values = values


class FakeGraph:
    """Simule un graphe qui s'arrête toujours avant 'approval'."""

    def __init__(self, excel_path=None, presentation_path=None):
        self.updated_with = None
        self.resumed = False
        # export_node ne produit ces chemins que lorsque l'analyse va au bout
        # (approuvée) -- un rejet ne les inclut donc jamais, ici comme dans
        # le vrai graphe (approval_check_node coupe court avant "export").
        self.excel_path = excel_path
        self.presentation_path = presentation_path

    def stream(self, state, config, stream_mode="values"):
        if state is None:
            # Reprise après update_state -- termine l'analyse.
            self.resumed = True
            status = AnalysisStatus.COMPLETED if self.updated_with else AnalysisStatus.FAILED
            yield {"status": status}
        else:
            yield {"status": AnalysisStatus.INSPECTION}

    def get_state(self, config):
        if self.resumed:
            status = AnalysisStatus.COMPLETED if self.updated_with else AnalysisStatus.FAILED
            values = {"status": status}
            if self.updated_with:
                values["excel_path"] = self.excel_path
                values["presentation_path"] = self.presentation_path
            return FakeSnapshot((), values)
        return FakeSnapshot(("approval",), {"status": AnalysisStatus.AWAITING_APPROVAL})

    def update_state(self, config, values):
        self.updated_with = values.get("approval_received")


def _patch_graph(monkeypatch, tmp_path, graphs: list):
    """Remplace build_agent_graph pour qu'il retourne un FakeGraph, dans l'ordre."""
    def fake_build(checkpoint_path=None):
        return graphs.pop(0)
    monkeypatch.setattr(agent.graph, "build_agent_graph", fake_build)


def _pipeline(tmp_path, **kwargs):
    return StreamingAnalysisPipeline(
        watch_dir=str(tmp_path / "stream"),
        db_path=str(tmp_path / "analytics.duckdb"),
        checkpoint_path=str(tmp_path / "checkpoint.db"),
        **kwargs,
    )


def test_first_arrival_triggers_analysis_despite_no_history(monkeypatch, tmp_path):
    graphs = [FakeGraph()]
    _patch_graph(monkeypatch, tmp_path, graphs)
    pipeline = _pipeline(tmp_path, require_approval=False)
    monkeypatch.setattr(pipeline, "_row_count", lambda path: 100)

    pipeline.on_new_data("fichier1.csv")
    assert graphs == []  # le seul FakeGraph fourni a bien été consommé


def test_constant_volume_does_not_trigger_analysis(monkeypatch, tmp_path):
    # Régression : "pas_de_variance" est le cas le plus normal (nouvelle
    # valeur identique à un historique déjà constant), pas un signal de
    # déclenchement. Les 2 premiers appels bootstrapent ("pas_assez_de_donnees",
    # len(history) < 3) et déclenchent chacun une analyse ; à partir du 3e,
    # l'historique est constant (std=0) et plus aucun déclenchement ne doit
    # avoir lieu.
    graphs = [FakeGraph(), FakeGraph()]
    _patch_graph(monkeypatch, tmp_path, graphs)
    pipeline = _pipeline(tmp_path, require_approval=False)
    monkeypatch.setattr(pipeline, "_row_count", lambda path: 100)

    for i in range(6):
        pipeline.on_new_data(f"fichier{i}.csv")

    assert graphs == []  # exactement les 2 déclenchements de bootstrap, pas plus


def test_real_anomaly_triggers_analysis(monkeypatch, tmp_path):
    # 2 déclenchements de bootstrap (len(history) < 3) + 1 déclenchement pour
    # le pic anormal au 6e appel.
    graphs = [FakeGraph(), FakeGraph(), FakeGraph()]
    _patch_graph(monkeypatch, tmp_path, graphs)
    pipeline = _pipeline(tmp_path, require_approval=False)

    counts = iter([100] * 5 + [100000])  # 5 valeurs stables puis un pic
    monkeypatch.setattr(pipeline, "_row_count", lambda path: next(counts))

    for i in range(6):
        pipeline.on_new_data(f"fichier{i}.csv")

    assert graphs == []


def test_auto_approval_mode_resumes_without_pending(monkeypatch, tmp_path):
    fake = FakeGraph()
    _patch_graph(monkeypatch, tmp_path, [fake])
    pipeline = _pipeline(tmp_path, require_approval=False)
    monkeypatch.setattr(pipeline, "_row_count", lambda path: 100)

    pipeline.on_new_data("fichier1.csv")

    assert fake.updated_with is True
    assert fake.resumed is True
    assert pipeline.pending == {}


def test_explicit_approval_mode_holds_pending_until_approved(monkeypatch, tmp_path):
    fake = FakeGraph()
    _patch_graph(monkeypatch, tmp_path, [fake])
    pipeline = _pipeline(tmp_path, require_approval=True)
    monkeypatch.setattr(pipeline, "_row_count", lambda path: 100)

    pipeline.on_new_data("fichier1.csv")

    assert len(pipeline.pending) == 1
    assert fake.resumed is False

    thread_id = next(iter(pipeline.pending))
    final = pipeline.approve(thread_id)

    assert fake.updated_with is True
    assert final["status"] == AnalysisStatus.COMPLETED
    assert pipeline.pending == {}


def test_reject_resumes_with_approval_false(monkeypatch, tmp_path):
    fake = FakeGraph()
    _patch_graph(monkeypatch, tmp_path, [fake])
    pipeline = _pipeline(tmp_path, require_approval=True)
    monkeypatch.setattr(pipeline, "_row_count", lambda path: 100)

    pipeline.on_new_data("fichier1.csv")
    thread_id = next(iter(pipeline.pending))
    final = pipeline.reject(thread_id)

    assert fake.updated_with is False
    assert final["status"] == AnalysisStatus.FAILED


# --- Livrables (Excel/PPTX) des analyses déclenchées par le streaming ---

def _fake_deliverable(tmp_path, name):
    """Crée un fichier factice à l'emplacement qu'aurait produit export_node."""
    path = tmp_path / "export_source" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("contenu factice")
    return str(path)


def test_row_count_does_not_execute_injected_sql_via_file_path(tmp_path):
    # Le nom du fichier déposé dans le dossier surveillé n'est pas assaini
    # (contrairement au mode agent Streamlit) : un chemin contenant une
    # apostrophe sortait du littéral SQL de read_csv_auto() et pouvait
    # renvoyer une valeur arbitraire (faussant la décision de l'AnomalyDetector)
    # au lieu du vrai nombre de lignes -- confirmé exploitable par test
    # manuel avant le passage à un paramètre lié (`?`).
    real_csv = tmp_path / "normal.csv"
    real_csv.write_text("a,b\n1,2\n3,4\n")
    malicious_path = f"{real_csv}') UNION SELECT 999999999 --"

    pipeline = _pipeline(tmp_path)
    with pytest.raises(Exception, match="No files found|IO Error"):
        pipeline._row_count(malicious_path)


def test_report_deliverables_is_a_noop_without_excel_or_pptx(tmp_path):
    pipeline = _pipeline(tmp_path)
    pipeline._report_deliverables("data/source.csv", {"status": AnalysisStatus.COMPLETED})
    assert not Path(pipeline.deliverables_dir).exists()


def test_report_deliverables_copies_and_renames_after_source_file(tmp_path):
    excel = _fake_deliverable(tmp_path, "rapport_20260101_120000.xlsx")
    pptx = _fake_deliverable(tmp_path, "presentation_20260101_120000.pptx")
    pipeline = _pipeline(tmp_path, deliverables_dir=str(tmp_path / "livrables"))

    pipeline._report_deliverables(
        "data/stream/ventes_quotidiennes.csv",
        {"excel_path": excel, "presentation_path": pptx},
    )

    dest_dir = Path(pipeline.deliverables_dir)
    assert (dest_dir / "ventes_quotidiennes_rapport_20260101_120000.xlsx").read_text() == "contenu factice"
    assert (dest_dir / "ventes_quotidiennes_presentation_20260101_120000.pptx").exists()
    # Le fichier généré par export_node reste en place (copie, pas déplacement) --
    # d'autres appelants (Streamlit, CLI) partagent le même dossier ./outputs.
    assert Path(excel).exists()


def test_on_new_data_reports_deliverables_after_auto_approval(monkeypatch, tmp_path):
    excel = _fake_deliverable(tmp_path, "rapport.xlsx")
    fake = FakeGraph(excel_path=excel, presentation_path=None)
    _patch_graph(monkeypatch, tmp_path, [fake])
    pipeline = _pipeline(tmp_path, require_approval=False, deliverables_dir=str(tmp_path / "livrables"))
    monkeypatch.setattr(pipeline, "_row_count", lambda path: 100)

    pipeline.on_new_data(str(tmp_path / "ventes.csv"))

    assert (Path(pipeline.deliverables_dir) / "ventes_rapport.xlsx").exists()


def test_approve_reports_deliverables_for_pending_analysis(monkeypatch, tmp_path):
    excel = _fake_deliverable(tmp_path, "rapport.xlsx")
    pptx = _fake_deliverable(tmp_path, "presentation.pptx")
    fake = FakeGraph(excel_path=excel, presentation_path=pptx)
    _patch_graph(monkeypatch, tmp_path, [fake])
    pipeline = _pipeline(tmp_path, require_approval=True, deliverables_dir=str(tmp_path / "livrables"))
    monkeypatch.setattr(pipeline, "_row_count", lambda path: 100)

    pipeline.on_new_data(str(tmp_path / "ventes.csv"))
    thread_id = next(iter(pipeline.pending))
    pipeline.approve(thread_id)

    dest_dir = Path(pipeline.deliverables_dir)
    assert (dest_dir / "ventes_rapport.xlsx").exists()
    assert (dest_dir / "ventes_presentation.pptx").exists()


def test_reject_produces_no_deliverables(monkeypatch, tmp_path):
    fake = FakeGraph(excel_path=_fake_deliverable(tmp_path, "rapport.xlsx"))
    _patch_graph(monkeypatch, tmp_path, [fake])
    pipeline = _pipeline(tmp_path, require_approval=True, deliverables_dir=str(tmp_path / "livrables"))
    monkeypatch.setattr(pipeline, "_row_count", lambda path: 100)

    pipeline.on_new_data(str(tmp_path / "ventes.csv"))
    thread_id = next(iter(pipeline.pending))
    pipeline.reject(thread_id)

    # FakeGraph n'inclut excel_path que si updated_with (approuvé) est vrai --
    # un rejet ne doit donc produire aucun livrable, comme le vrai graphe.
    assert not Path(pipeline.deliverables_dir).exists()
