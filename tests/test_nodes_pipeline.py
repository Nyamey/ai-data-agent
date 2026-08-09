# tests/test_nodes_pipeline.py — Nœuds build/test/validate/approval (pas de LLM)
from agent.nodes.approval import approval_check_node, format_inspection_summary
from agent.nodes.build import build_node
from agent.nodes.test import test_node as run_test_node
from agent.nodes.validate import validate_node
from agent.state import AgentState, AnalysisStatus
from agent.tools.data_loader import load_data


def _inspected_state(csv_path, tmp_path, **overrides):
    db_path = str(tmp_path / "analytics.duckdb")
    meta = load_data(csv_path, db_path=db_path)
    defaults = dict(
        query="q", data_path=csv_path, data_metadata=meta,
        business_question="q", metric_definition="m", comparison_period="p",
    )
    defaults.update(overrides)
    return AgentState(**defaults)


def test_build_node_computes_weekly_metric_when_date_and_id_present(sample_retention_csv, tmp_path):
    state = _inspected_state(sample_retention_csv, tmp_path)
    result = build_node(state)
    assert result["status"] == AnalysisStatus.TESTING
    assert "semaine" in result["weekly_retention"]["data"] or "valeur" in result["weekly_retention"]["data"]
    assert "query" in result["weekly_retention"]


def test_build_node_falls_back_to_row_count_without_id_or_date(sample_no_id_csv, tmp_path):
    state = _inspected_state(sample_no_id_csv, tmp_path)
    result = build_node(state)
    assert "aucune colonne date détectée" in result["weekly_retention"]["label"]


def test_test_node_flags_significant_dimension(tmp_path):
    # Répartition extrêmement déséquilibrée entre 2 catégories -> chi² doit
    # détecter une différence statistiquement significative (p < 0.05).
    import pandas as pd
    df = pd.DataFrame({
        "customer_id": range(1, 101),
        "platform": ["mobile"] * 95 + ["web"] * 5,
    })
    csv_path = tmp_path / "skewed.csv"
    df.to_csv(csv_path, index=False)
    state = _inspected_state(str(csv_path), tmp_path)

    result = run_test_node(state)
    assert result["status"] == AnalysisStatus.VALIDATING
    assert "platform" in result["statistical_tests"]
    assert result["statistical_tests"]["platform"]["significant"] is True
    assert result["statistical_tests"]["platform"]["p_value"] < 0.05


def test_test_node_does_not_flag_balanced_dimension(tmp_path):
    import pandas as pd
    df = pd.DataFrame({
        "customer_id": range(1, 101),
        "platform": ["mobile", "web"] * 50,
    })
    csv_path = tmp_path / "balanced.csv"
    df.to_csv(csv_path, index=False)
    state = _inspected_state(str(csv_path), tmp_path)

    result = run_test_node(state)
    assert result["statistical_tests"]["platform"]["significant"] is False


def test_validate_node_reports_duplicates_check(sample_retention_csv, tmp_path):
    state = _inspected_state(sample_retention_csv, tmp_path)
    result = validate_node(state)
    assert result["status"] == AnalysisStatus.RECOMMENDING
    assert result["validation_checks"]["doublons"]["passed"] is True
    assert "total_entites" in result["validation_checks"]


def test_validate_node_uses_row_count_when_no_id_column(sample_no_id_csv, tmp_path):
    state = _inspected_state(sample_no_id_csv, tmp_path)
    result = validate_node(state)
    assert "total_lignes" in result["validation_checks"]
    assert "total_entites" not in result["validation_checks"]


def test_approval_check_node_approved_moves_to_building():
    state = AgentState(query="q", data_path="p.csv", approval_received=True)
    result = approval_check_node(state)
    assert result["status"] == AnalysisStatus.BUILDING


def test_approval_check_node_rejected_moves_to_failed():
    state = AgentState(query="q", data_path="p.csv", approval_received=False)
    result = approval_check_node(state)
    assert result["status"] == AnalysisStatus.FAILED
    assert "rejetée" in result["errors"][0]


def test_format_inspection_summary_includes_metadata(sample_retention_csv, tmp_path):
    state = _inspected_state(sample_retention_csv, tmp_path)
    summary = format_inspection_summary(state)
    assert "Question" in summary
    assert str(state.data_metadata["row_count"]) in summary
