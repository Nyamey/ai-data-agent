# tests/test_app_integration.py — Intégration Streamlit de bout en bout
#
# Contrairement aux tests unitaires (agent_ui.py, simple_mode_ui.py testés
# indirectement ailleurs via leurs briques), ceux-ci pilotent réellement les
# widgets Streamlit via AppTest -- upload non simulable, donc les fichiers
# sont injectés via des scripts dans tests/streamlit_scripts/ qui appellent
# directement render_agent_mode()/render_simple_mode(). Le graphe LangGraph
# est remplacé par un faux graphe (FakeGraph) pour rester rapide et
# déterministe ; litellm.completion est simulé pour le mode simple, par le
# même principe que tests/test_framing_recommend.py.
import os
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

import agent_ui

AGENT_HARNESS = str(Path(__file__).parent / "streamlit_scripts" / "agent_mode_harness.py")
SIMPLE_HARNESS = str(Path(__file__).parent / "streamlit_scripts" / "simple_mode_harness.py")


class FakeSnapshot:
    def __init__(self, next_nodes, values):
        self.next = next_nodes
        self.values = values


class FakeAgentGraph:
    """Simule le graphe LangGraph pour l'UI : inspection -> approbation -> résultats.

    Contrairement au FakeGraph de test_streaming_pipeline.py (qui ne
    vérifie que la décision de déclenchement), celui-ci renvoie des données
    de cadrage/inspection/résultats assez réalistes pour que
    _render_single_agent_run() les affiche sans branche manquante.
    """

    def __init__(self, row_count=20, id_column="id", excel_path=None, presentation_path=None,
                 null_counts=None, date_range=None):
        self.resumed = False
        self.approval_received = None
        self.row_count = row_count
        self.id_column = id_column
        self.excel_path = excel_path
        self.presentation_path = presentation_path
        self.null_counts = null_counts or {}
        self.date_range = date_range or {}

    def _final_values(self):
        """État final complet -- même forme que ce que renverrait le vrai
        graphe, que ce soit via le dernier événement de stream(None, ...)
        (stream_mode="values" yield l'état accumulé à chaque étape, donc son
        dernier élément a la même forme que get_state().values) ou via
        get_state() directement. Les deux DOIVENT être cohérents ici aussi,
        sinon ce faux graphe ne reproduirait pas fidèlement ce sur quoi
        _render_single_agent_run() se base réellement."""
        if not self.approval_received:
            return {"status": "echec", "errors": ["Analyse rejetée par l'utilisateur"]}
        return {
            "status": "termine",
            "errors": [],
            "weekly_retention": {"data": "| valeur |\n|---:|\n| 42 |", "label": "Résultat"},
            "driver_analysis": [{"dimension": "region", "result": "| region | n |\n|---|---|\n| EU | 10 |"}],
            "statistical_tests": {"region": {"significant": True, "p_value": 0.01}},
            "validation_checks": {"doublons": {"result": 0, "passed": True}},
            "recommendations": [
                {"title": "Recommandation test", "description": "Détail.",
                 "impact": "élevé", "feasibility": "moyenne", "timeline": "court terme"},
            ],
            "excel_path": self.excel_path,
            "presentation_path": self.presentation_path,
        }

    def stream(self, state, config, stream_mode="values"):
        if state is None:
            self.resumed = True
            yield self._final_values()
        else:
            yield {"status": "inspection"}

    def get_state(self, config):
        if self.resumed:
            return FakeSnapshot((), self._final_values())
        return FakeSnapshot(("approval",), {
            "status": "en_attente_approbation",
            "business_question": "Question reformulée factice",
            "metric_definition": "Métrique factice",
            "comparison_period": "période factice",
            "assumptions": ["hypothèse factice"],
            "data_metadata": {
                "row_count": self.row_count,
                "schema": [{"column_name": "id"}, {"column_name": "valeur"}],
                "duplicate_count": 0,
                "id_column": self.id_column,
                "null_counts": self.null_counts,
                "date_range": self.date_range,
            },
        })

    def update_state(self, config, values):
        self.approval_received = values.get("approval_received")


def _patch_graph_factory(monkeypatch, **graph_kwargs):
    """Remplace build_agent_graph par une fabrique qui renvoie la MÊME
    instance de FakeAgentGraph pour un checkpoint_path donné.

    Indispensable dès qu'une analyse dépasse l'inspection : le clic sur
    Approuver/Rejeter appelle build_agent_graph() une seconde fois (avec le
    même checkpoint_path) pour reprendre l'exécution -- un simple `lambda
    checkpoint_path=None: FakeAgentGraph()` créerait une instance fraîche à
    chaque appel, perdant l'état d'approbation entre les deux, et avec
    plusieurs fichiers en cours mélangerait leurs graphes respectifs.
    """
    graphs_by_checkpoint = {}

    def fake_build(checkpoint_path=None):
        return graphs_by_checkpoint.setdefault(checkpoint_path, FakeAgentGraph(**graph_kwargs))

    monkeypatch.setattr(agent_ui, "build_agent_graph", fake_build)
    return graphs_by_checkpoint


def _write_csv(tmp_path, name, n=20):
    path = tmp_path / name
    pd.DataFrame({"id": range(1, n + 1), "valeur": range(n)}).to_csv(path, index=False)
    return str(path)


def _run_harness(monkeypatch, harness, csv_paths, query="Question de test", provider="Groq (Recommandé)"):
    monkeypatch.setenv("HARNESS_CSV_PATHS", os.pathsep.join(csv_paths))
    monkeypatch.setenv("HARNESS_QUERY", query)
    monkeypatch.setenv("HARNESS_PROVIDER", provider)
    at = AppTest.from_file(harness, default_timeout=60)
    at.run()
    assert not at.exception, f"Exception inattendue : {[str(e) for e in at.exception]}"
    return at


# --- Mode agent : fichier unique ---

def test_agent_mode_single_file_reaches_approval(monkeypatch, tmp_path):
    _patch_graph_factory(monkeypatch)
    csv_path = _write_csv(tmp_path, "ventes.csv")

    at = _run_harness(monkeypatch, AGENT_HARNESS, [csv_path])
    at.session_state["agent_trigger_inspect"] = True
    at.run()

    assert not at.exception
    run = at.session_state["agent_runs"]["0_ventes.csv"]
    assert run["awaiting_approval"] is True
    assert run["snapshot_values"]["business_question"] == "Question reformulée factice"
    approve_buttons = [b for b in at.button if b.key == "agent_approve_0_ventes.csv"]
    assert len(approve_buttons) == 1


def test_agent_mode_shows_missing_values_and_date_range_tables(monkeypatch, tmp_path):
    # meta["null_counts"]/["date_range"] vides (le cas par défaut des autres
    # tests) ne déclenchent jamais render_missing_values()/render_date_range() --
    # ce test vérifie spécifiquement le chemin où ces tableaux s'affichent.
    _patch_graph_factory(
        monkeypatch,
        null_counts={"segment": 3},
        date_range={"activity_date": {"min": "2024-01-01", "max": "2024-06-01"}},
    )
    csv_path = _write_csv(tmp_path, "ventes.csv")

    at = _run_harness(monkeypatch, AGENT_HARNESS, [csv_path])
    at.session_state["agent_trigger_inspect"] = True
    at.run()

    assert not at.exception
    assert len(at.warning) == 1  # render_missing_values() commence par st.warning(...)
    assert any("Plage de dates" in c.value for c in at.caption)  # render_date_range()
    assert len(at.dataframe) >= 2  # une table par fonction


def test_agent_mode_single_file_approve_shows_results_and_downloads(monkeypatch, tmp_path):
    excel = tmp_path / "rapport.xlsx"
    excel.write_bytes(b"contenu factice")
    _patch_graph_factory(monkeypatch, excel_path=str(excel))
    csv_path = _write_csv(tmp_path, "ventes.csv")

    at = _run_harness(monkeypatch, AGENT_HARNESS, [csv_path])
    at.session_state["agent_trigger_inspect"] = True
    at.run()
    at.button(key="agent_approve_0_ventes.csv").click().run()

    assert not at.exception
    assert len(at.success) == 1
    assert "Recommandation test" in "".join(m.value for m in at.markdown)
    dl_buttons = [b for b in at.download_button if b.key == "agent_dl_xlsx_0_ventes.csv"]
    assert len(dl_buttons) == 1


def test_agent_mode_chat_answers_a_followup_question(monkeypatch, tmp_path):
    # L'assistant conversationnel (agent/tools/chat_assistant.answer_question)
    # est mocké ici -- ses propres branches (décision needs_query, exécution
    # SQL, garde-fou lecture seule) sont testées à part dans
    # tests/test_chat_assistant.py. Ce test vérifie seulement le câblage
    # côté UI : historique affiché, SQL affichée si renvoyée, isolation par run_key.
    _patch_graph_factory(monkeypatch)
    csv_path = _write_csv(tmp_path, "ventes.csv")

    at = _run_harness(monkeypatch, AGENT_HARNESS, [csv_path])
    at.session_state["agent_trigger_inspect"] = True
    at.run()
    at.button(key="agent_approve_0_ventes.csv").click().run()
    assert not at.exception

    import agent_ui
    monkeypatch.setattr(
        agent_ui, "answer_question",
        lambda **kwargs: {"answer": "La plateforme mobile domine.", "sql": 'SELECT * FROM "t"'},
    )

    at.chat_input(key="chat_input_0_ventes.csv").set_value("Quelle plateforme domine ?").run()

    assert not at.exception
    all_markdown = "".join(m.value for m in at.markdown)
    assert "Quelle plateforme domine ?" in all_markdown
    assert "La plateforme mobile domine." in all_markdown
    assert any('SELECT * FROM "t"' in c.value for c in at.code)


def test_agent_mode_llm_unavailable_shows_warning_not_error(monkeypatch, tmp_path):
    from agent.llm.config import LLMUnavailableError

    def raise_unavailable(checkpoint_path=None):
        raise LLMUnavailableError("Le service d'analyse IA n'est pas configuré pour le moment.")

    monkeypatch.setattr(agent_ui, "build_agent_graph", raise_unavailable)
    csv_path = _write_csv(tmp_path, "ventes.csv")

    at = _run_harness(monkeypatch, AGENT_HARNESS, [csv_path])
    at.session_state["agent_trigger_inspect"] = True
    at.run()

    assert not at.exception
    assert len(at.error) == 0
    assert len(at.warning) == 1
    assert "pas configuré" in at.warning[0].value


# --- Mode agent : plusieurs fichiers, cycles indépendants ---

def test_agent_mode_independent_runs_are_isolated(monkeypatch, tmp_path):
    _patch_graph_factory(monkeypatch)

    csv_a = _write_csv(tmp_path, "a.csv")
    csv_b = _write_csv(tmp_path, "b.csv")

    at = _run_harness(monkeypatch, AGENT_HARNESS, [csv_a, csv_b])
    at.session_state["agent_trigger_inspect"] = True
    at.run()

    runs = at.session_state["agent_runs"]
    assert set(runs.keys()) == {"0_a.csv", "1_b.csv"}

    at.button(key="agent_approve_0_a.csv").click().run()
    at.button(key="agent_reject_1_b.csv").click().run()

    runs = at.session_state["agent_runs"]
    assert runs["0_a.csv"]["final_event"]["status"] == "termine"
    assert runs["1_b.csv"]["final_event"]["status"] == "echec"


# --- Mode agent : jointure ---

def test_agent_mode_join_flow_reaches_approval(monkeypatch, tmp_path):
    _patch_graph_factory(monkeypatch)
    csv_a = _write_csv(tmp_path, "a.csv")
    csv_b = _write_csv(tmp_path, "b.csv")

    at = _run_harness(monkeypatch, AGENT_HARNESS, [csv_a, csv_b])
    at.radio(key="agent_join_mode_choice").set_value("Croisés par jointure (un seul cycle)").run()
    assert not at.exception

    at.session_state["agent_trigger_inspect"] = True
    at.run()

    assert not at.exception
    assert "join_0" in at.session_state["agent_runs"]
    assert at.session_state["agent_runs"]["join_0"]["awaiting_approval"] is True


# --- Mode simple ---

def test_simple_mode_analysis_flow_shows_result_and_downloads(monkeypatch, tmp_path):
    class FakeChoice:
        def __init__(self, content):
            self.message = type("Msg", (), {"content": content})()

    class FakeResponse:
        def __init__(self, content):
            self.choices = [FakeChoice(content)]

    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    import simple_mode_ui
    monkeypatch.setattr(
        simple_mode_ui, "completion",
        lambda **kwargs: FakeResponse("Analyse factice : tout va bien."),
    )
    csv_path = _write_csv(tmp_path, "ventes.csv")

    at = _run_harness(monkeypatch, SIMPLE_HARNESS, [csv_path])

    assert not at.exception
    assert len(at.error) == 0
    assert "Analyse factice" in "".join(m.value for m in at.markdown)
    assert len(at.download_button) == 4


def test_simple_mode_llm_unavailable_shows_warning_not_error(monkeypatch, tmp_path):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    import simple_mode_ui
    monkeypatch.setattr(
        simple_mode_ui, "completion",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("panne simulée")),
    )
    csv_path = _write_csv(tmp_path, "ventes.csv")

    at = _run_harness(monkeypatch, SIMPLE_HARNESS, [csv_path])

    assert not at.exception
    assert len(at.error) == 0
    assert len(at.warning) == 1
    assert "indisponibles" in at.warning[0].value
