# tests/test_data_loader.py — Chargement DuckDB et détection de schéma
import pandas as pd
import pytest

from agent.tools.data_loader import detect_id_column, execute_query, fetch_dataframe, load_data


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
