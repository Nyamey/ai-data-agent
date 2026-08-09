# tests/test_data_loader.py — Chargement DuckDB et détection de schéma
import duckdb
import pandas as pd

from agent.tools.data_loader import detect_id_column, execute_query, fetch_dataframe, load_data, quote_ident


def test_detect_id_column_matches_common_patterns():
    schema = [{"column_name": "customer_id"}, {"column_name": "region"}]
    assert detect_id_column(schema, []) == "customer_id"


def test_detect_id_column_matches_bare_id():
    schema = [{"column_name": "id"}, {"column_name": "nom"}]
    assert detect_id_column(schema, []) == "id"


def test_detect_id_column_excludes_date_columns():
    schema = [{"column_name": "date_id"}, {"column_name": "region"}]
    assert detect_id_column(schema, ["date_id"]) is None


def test_detect_id_column_returns_none_when_absent():
    schema = [{"column_name": "produit"}, {"column_name": "prix"}]
    assert detect_id_column(schema, []) is None


def test_load_data_returns_full_metadata(sample_retention_csv, tmp_path):
    db_path = str(tmp_path / "analytics.duckdb")
    meta = load_data(sample_retention_csv, db_path=db_path)

    assert meta["row_count"] == 40
    assert meta["id_column"] == "customer_id"
    assert "activity_date" in meta["date_range"]
    assert meta["duplicate_count"] == 0
    assert meta["db_path"] == db_path
    columns = {s["column_name"] for s in meta["schema"]}
    assert columns == {"customer_id", "activity_date", "platform", "region"}


def test_load_data_without_id_or_date_column(sample_no_id_csv, tmp_path):
    db_path = str(tmp_path / "analytics.duckdb")
    meta = load_data(sample_no_id_csv, db_path=db_path)

    assert meta["id_column"] is None
    assert meta["date_range"] == {}
    assert meta["row_count"] == 40


def test_load_data_detects_missing_values(tmp_path):
    df = pd.DataFrame({"a": [1, 2, None], "b": ["x", None, "z"]})
    csv_path = tmp_path / "with_nulls.csv"
    df.to_csv(csv_path, index=False)
    db_path = str(tmp_path / "analytics.duckdb")

    meta = load_data(str(csv_path), db_path=db_path)
    assert meta["null_counts"] == {"a": 1, "b": 1}


def test_load_data_detects_duplicates(tmp_path):
    df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
    csv_path = tmp_path / "with_dupes.csv"
    df.to_csv(csv_path, index=False)
    db_path = str(tmp_path / "analytics.duckdb")

    meta = load_data(str(csv_path), db_path=db_path)
    assert meta["duplicate_count"] == 1


def test_fetch_dataframe_returns_pandas_dataframe(sample_retention_csv, tmp_path):
    db_path = str(tmp_path / "analytics.duckdb")
    meta = load_data(sample_retention_csv, db_path=db_path)
    df = fetch_dataframe(f"SELECT COUNT(*) as total FROM {meta['table_name']}", db_path=db_path)
    assert isinstance(df, pd.DataFrame)
    assert df["total"].iloc[0] == 40


def test_execute_query_returns_markdown(sample_retention_csv, tmp_path):
    db_path = str(tmp_path / "analytics.duckdb")
    meta = load_data(sample_retention_csv, db_path=db_path)
    result = execute_query(f"SELECT COUNT(*) as total FROM {meta['table_name']}", db_path=db_path)
    assert "total" in result
    assert "|" in result  # tableau markdown


def test_execute_query_returns_error_string_on_bad_sql(tmp_path):
    db_path = str(tmp_path / "analytics.duckdb")
    result = execute_query("SELECT * FROM table_qui_nexiste_pas", db_path=db_path)
    assert result.startswith("Erreur SQL")


def test_quote_ident_escapes_embedded_quotes():
    assert quote_ident('a"b') == '"a""b"'


def test_quote_ident_neutralizes_sql_injection_attempt():
    # Régression : un nom de colonne comme celui-ci matche en plus le motif
    # de détection de colonne identifiant (suffixe "_id") -- confirmé
    # exploitable par test manuel avant l'ajout de quote_ident().
    malicious = "1) as total FROM data UNION SELECT flag as total FROM secrets -- x_id"
    assert quote_ident(malicious) == f'"{malicious}"'


def test_load_data_does_not_leak_data_via_malicious_column_name(tmp_path):
    # Reproduit l'attaque trouvée en revue de sécurité : un CSV dont la
    # colonne s'appelle littéralement une tentative d'injection SQL ne doit
    # ni planter l'inspection, ni permettre de lire une autre table DuckDB.
    malicious_col = "1) as total FROM data UNION SELECT flag as total FROM secrets -- x_id"
    df = pd.DataFrame({malicious_col: [1, 2, 3], "valeur": [10, 20, 30]})
    csv_path = tmp_path / "malicious.csv"
    df.to_csv(csv_path, index=False)

    db_path = str(tmp_path / "analytics.duckdb")
    con = duckdb.connect(db_path)
    con.execute("CREATE TABLE secrets AS SELECT 'FUITE_DE_DONNEES' as flag")
    con.close()

    meta = load_data(str(csv_path), db_path=db_path)
    assert meta["id_column"] == malicious_col  # détecté (suffixe "_id"), mais neutralisé à l'usage
    assert meta["row_count"] == 3
    assert meta["null_counts"] == {}


def test_build_and_validate_nodes_survive_malicious_column_name(tmp_path):
    from agent.nodes.build import build_node
    from agent.nodes.validate import validate_node
    from agent.state import AgentState

    malicious_col = "1) as total FROM data UNION SELECT flag as total FROM secrets -- x_id"
    df = pd.DataFrame({malicious_col: [1, 2, 3], "valeur": [10, 20, 30]})
    csv_path = tmp_path / "malicious.csv"
    df.to_csv(csv_path, index=False)

    db_path = str(tmp_path / "analytics.duckdb")
    con = duckdb.connect(db_path)
    con.execute("CREATE TABLE secrets AS SELECT 'FUITE_DE_DONNEES' as flag")
    con.close()

    meta = load_data(str(csv_path), db_path=db_path)
    state = AgentState(query="q", data_path=str(csv_path), data_metadata=meta)

    build_result = build_node(state)
    assert "FUITE_DE_DONNEES" not in build_result["weekly_retention"]["data"]

    validate_result = validate_node(state)
    total_check = str(validate_result["validation_checks"]["total_entites"])
    assert "FUITE_DE_DONNEES" not in total_check
