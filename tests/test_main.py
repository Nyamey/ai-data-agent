# tests/test_main.py : point d'entrée CLI (jamais couvert par un test avant ce fichier)
#
# Comme pour les tests d'intégration Streamlit, le graphe LangGraph est
# remplacé par un faux graphe déterministe pour rester rapide et
# network-free ; seul le point d'interruption humain (input()) et le
# rendu de la progression sont ici sous test, pas le contenu réel d'une
# analyse (couvert ailleurs, node par node).
import agent.main
from agent.main import _print_progress, run_analysis
from agent.state import AnalysisStatus


class FakeSnapshot:
    def __init__(self, next_nodes, values):
        self.next = next_nodes
        self.values = values


class FakeMainGraph:
    """Simule le graphe pour agent.main.run_analysis().

    stops_before_approval=False permet de simuler une inspection qui se
    termine directement en erreur, sans jamais atteindre le point
    d'interruption -- run_analysis() ne doit alors jamais appeler input().
    """

    def __init__(self, stops_before_approval=True):
        self.stops_before_approval = stops_before_approval
        self.approval_received = None
        self.updated = False

    def stream(self, state, config, stream_mode="values"):
        if state is None:
            self.updated = True
            status = AnalysisStatus.COMPLETED if self.approval_received else AnalysisStatus.FAILED
            yield {
                "status": status,
                "audit_trail": ["Approbation reçue" if self.approval_received else "Analyse rejetée"],
                "recommendations": [{"title": "Reco factice", "description": "d",
                                      "impact": "élevé", "feasibility": "moyenne", "timeline": "court terme"}]
                if self.approval_received else [],
                "errors": [] if self.approval_received else ["Analyse rejetée par l'utilisateur"],
            }
        else:
            yield {"status": AnalysisStatus.INSPECTION, "audit_trail": ["Inspection en cours"]}

    def get_state(self, config):
        if self.updated:
            return FakeSnapshot((), {})
        if self.stops_before_approval:
            return FakeSnapshot(("approval",), {
                "query": "q",
                "business_question": "Question factice", "metric_definition": "Métrique factice",
                "comparison_period": "période factice", "data_path": "data.csv",
                "data_metadata": {"row_count": 10, "schema": [], "duplicate_count": 0,
                                   "null_counts": {}, "date_range": {}},
                "needs_aggregation": False, "assumptions": [],
            })
        return FakeSnapshot((), {})

    def update_state(self, config, values):
        self.approval_received = values.get("approval_received")


def test_print_progress_handles_missing_audit_trail(capsys):
    _print_progress({"status": AnalysisStatus.INSPECTION})
    out = capsys.readouterr().out
    assert "inspection" in out.lower()


def test_print_progress_shows_last_audit_entry(capsys):
    _print_progress({"status": AnalysisStatus.TESTING, "audit_trail": ["a", "b", "dernière étape"]})
    out = capsys.readouterr().out
    assert "dernière étape" in out


def test_run_analysis_approves_via_input_and_completes(monkeypatch):
    fake = FakeMainGraph()
    monkeypatch.setattr(agent.main, "build_agent_graph", lambda **kwargs: fake)
    monkeypatch.setattr("builtins.input", lambda prompt: "oui")

    result = run_analysis(query="q", data_path="data.csv")

    assert fake.approval_received is True
    assert result["status"] == AnalysisStatus.COMPLETED
    assert len(result["recommendations"]) == 1


def test_run_analysis_rejects_on_non_affirmative_input(monkeypatch):
    fake = FakeMainGraph()
    monkeypatch.setattr(agent.main, "build_agent_graph", lambda **kwargs: fake)
    monkeypatch.setattr("builtins.input", lambda prompt: "non")

    result = run_analysis(query="q", data_path="data.csv")

    assert fake.approval_received is False
    assert result["status"] == AnalysisStatus.FAILED
    assert result["errors"] == ["Analyse rejetée par l'utilisateur"]


def test_run_analysis_never_prompts_when_graph_ends_before_approval(monkeypatch):
    fake = FakeMainGraph(stops_before_approval=False)
    monkeypatch.setattr(agent.main, "build_agent_graph", lambda **kwargs: fake)

    def fail_if_called(prompt):
        raise AssertionError("input() ne doit pas être appelé si le graphe n'atteint pas l'approbation")

    monkeypatch.setattr("builtins.input", fail_if_called)

    result = run_analysis(query="q", data_path="data.csv")

    assert fake.updated is False
    assert result["status"] == AnalysisStatus.INSPECTION


def test_run_analysis_passes_through_optional_params(monkeypatch):
    captured = {}

    def fake_build(**kwargs):
        captured["build_kwargs"] = kwargs
        return FakeMainGraph(stops_before_approval=False)

    monkeypatch.setattr(agent.main, "build_agent_graph", fake_build)

    run_analysis(
        query="q", data_path="data.csv", db_path="custom.duckdb",
        checkpoint_path="custom_checkpoint.db", llm_provider="mistral",
    )

    assert captured["build_kwargs"] == {"checkpoint_path": "custom_checkpoint.db"}
