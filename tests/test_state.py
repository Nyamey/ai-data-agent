# tests/test_state.py : schéma d'état de l'agent
from agent.state import AgentState, AnalysisStatus


def test_agent_state_has_sane_defaults():
    state = AgentState(query="Pourquoi la rétention baisse-t-elle ?", data_path="data/x.csv")
    assert state.status == AnalysisStatus.PENDING
    assert state.output_language == "fr"
    assert state.db_path is None
    assert state.llm_provider is None
    assert state.assumptions == []
    assert state.audit_trail == []
    assert state.errors == []
    assert state.iterations == 0
    assert state.max_iterations == 3


def test_agent_state_accepts_optional_fields():
    state = AgentState(
        query="q", data_path="p.csv", db_path="/tmp/x.duckdb", llm_provider="groq",
    )
    assert state.db_path == "/tmp/x.duckdb"
    assert state.llm_provider == "groq"


def test_analysis_status_values_are_stable_strings():
    # Ces valeurs sont sérialisées dans les checkpoints SQLite (langgraph) --
    # les changer casserait la reprise d'analyses en cours.
    assert AnalysisStatus.PENDING.value == "en_attente"
    assert AnalysisStatus.AWAITING_APPROVAL.value == "en_attente_approbation"
    assert AnalysisStatus.EXPORTING.value == "export"
    assert AnalysisStatus.COMPLETED.value == "termine"
    assert AnalysisStatus.FAILED.value == "echec"
