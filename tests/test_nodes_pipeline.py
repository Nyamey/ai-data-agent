# tests/test_nodes_pipeline.py — Nœuds build/test/validate/approval (pas de LLM)
from agent.nodes.approval import approval_check_node, format_inspection_summary
from agent.nodes.build import build_node
from agent.nodes.inspection import inspection_node
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


def test_test_node_skips_high_cardinality_dimension(tmp_path):
    # Une colonne quasi unique par ligne (ex. un second identifiant, un
    # commentaire libre) n'est pas une dimension de comparaison exploitable :
    # le chi² d'ajustement y détecterait presque toujours un écart
    # "significatif" sans rien dire d'utile. Régression : avant le garde-fou
    # de cardinalité, une telle colonne polluait driver_analysis avec une
    # table à une ligne par catégorie et un faux signal statistique.
    import pandas as pd
    from agent.nodes.test import MAX_DIMENSION_CATEGORIES

    n = MAX_DIMENSION_CATEGORIES + 5
    df = pd.DataFrame({
        "customer_id": range(1, n + 1),
        "commentaire_libre": [f"note-{i}" for i in range(n)],  # n catégories distinctes
        "platform": (["mobile", "web"] * n)[:n],
    })
    csv_path = tmp_path / "high_cardinality.csv"
    df.to_csv(csv_path, index=False)
    state = _inspected_state(str(csv_path), tmp_path)

    result = run_test_node(state)

    by_dimension = {d["dimension"]: d for d in result["driver_analysis"]}
    assert "skipped" in by_dimension["commentaire_libre"]
    assert "commentaire_libre" not in result["statistical_tests"]
    # Les dimensions exclues n'ont pas de "query" -- export_node (qui teste
    # d.get("query")) les ignore donc naturellement, sans branche dédiée.
    assert "query" not in by_dimension["commentaire_libre"]
    # Une dimension normale à côté ne doit pas être affectée par le garde-fou.
    assert "platform" in result["statistical_tests"]


def test_test_node_records_error_for_a_dimension_that_fails(tmp_path):
    # Contrairement à execute_query() (utilisée par build/validate, qui
    # absorbe ses propres erreurs), fetch_dataframe() lève réellement --
    # test_node doit donc rattraper l'échec d'UNE dimension sans faire
    # échouer les autres. Une colonne annoncée dans le schéma mais absente
    # de la vraie table force cet échec.
    import pandas as pd
    df = pd.DataFrame({"customer_id": range(1, 21), "platform": ["mobile", "web"] * 10})
    csv_path = tmp_path / "data.csv"
    df.to_csv(csv_path, index=False)
    state = _inspected_state(str(csv_path), tmp_path)
    state.data_metadata["schema"].append({"column_name": "colonne_fantome", "column_type": "VARCHAR"})

    result = run_test_node(state)

    by_dimension = {d["dimension"]: d for d in result["driver_analysis"]}
    assert "error" in by_dimension["colonne_fantome"]
    assert "platform" in by_dimension and "error" not in by_dimension["platform"]


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


def test_validate_node_marks_check_failed_when_query_errors(sample_retention_csv, tmp_path):
    # Régression : execute_query() absorbe ses propres exceptions et renvoie
    # une chaîne "Erreur SQL: ..." plutôt que de lever -- un ancien
    # try/except autour de ses appels ne s'exécutait donc jamais, et
    # "passed" restait à True même quand la requête sous-jacente échouait
    # (visible uniquement dans le texte du résultat). Ici, un nom de table
    # inexistant force cet échec.
    state = _inspected_state(sample_retention_csv, tmp_path)
    state.data_metadata["table_name"] = "table_qui_nexiste_pas"

    result = validate_node(state)

    check = result["validation_checks"]["total_entites"]
    assert check["passed"] is False
    assert "Erreur SQL" in check["result"]


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


def test_format_inspection_summary_surfaces_join_warning(sample_retention_csv, tmp_path):
    state = _inspected_state(sample_retention_csv, tmp_path)
    state.data_metadata["join_warning"] = "La jointure ne produit aucune ligne."

    summary = format_inspection_summary(state)

    assert "ATTENTION" in summary
    assert "La jointure ne produit aucune ligne." in summary


def test_inspection_node_uses_load_data_without_join_spec(sample_retention_csv, tmp_path):
    state = AgentState(query="q", data_path=sample_retention_csv, db_path=str(tmp_path / "a.duckdb"))
    result = inspection_node(state)
    assert result["status"] == AnalysisStatus.AWAITING_APPROVAL
    assert result["data_metadata"]["row_count"] == 40
    assert "source_files" not in result["data_metadata"]


def test_inspection_node_uses_load_joined_data_with_join_spec(sample_joinable_csvs, tmp_path):
    paths = sample_joinable_csvs
    join_spec = {
        "root": paths["commandes"],
        "joins": [
            {"file": paths["clients"], "on_file": paths["commandes"],
             "file_column": "id", "on_column": "client_id_ref", "how": "inner"},
        ],
    }
    state = AgentState(
        query="q", data_path=paths["commandes"],
        data_paths=[paths["commandes"], paths["clients"]], join_spec=join_spec,
        db_path=str(tmp_path / "a.duckdb"),
    )
    result = inspection_node(state)
    assert result["status"] == AnalysisStatus.AWAITING_APPROVAL
    assert result["data_metadata"]["source_files"] == [paths["commandes"], paths["clients"]]
    columns = {s["column_name"] for s in result["data_metadata"]["schema"]}
    assert "commandes__montant" in columns
    assert "clients__segment" in columns


# Le cas "framing_node mentionne bien tous les fichiers joints dans son
# prompt" est couvert par tests/test_framing_recommend.py, qui exerce en
# plus le vrai chemin get_llm_response()/extract_json() (pas juste
# get_llm_response mocké en bloc).
