# tests/test_mcp_server.py : serveur MCP DuckDB, restriction en lecture seule
#
# execute_query() est exposée à des assistants IA externes (Claude Desktop,
# VS Code Copilot...) -- ces tests couvrent le garde-fou qui l'empêche
# d'exécuter autre chose qu'une requête de lecture (voir _ensure_read_only()
# dans mcp_server/server.py).
import pytest

from mcp_server.server import _ensure_read_only, execute_query, health_check


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "  select * from t",
    "WITH x AS (SELECT 1) SELECT * FROM x",
    "DESCRIBE t",
    "SHOW TABLES",
    "EXPLAIN SELECT 1",
    "SELECT 1;",  # un point-virgule final seul (pas une deuxième instruction) reste accepté
])
def test_ensure_read_only_accepts_read_queries(sql):
    _ensure_read_only(sql)  # ne doit pas lever


@pytest.mark.parametrize("sql", [
    "DROP TABLE t",
    "DELETE FROM t",
    "INSERT INTO t VALUES (1)",
    "UPDATE t SET x = 1",
    "CREATE TABLE t (x INT)",
    "ALTER TABLE t ADD COLUMN y INT",
    "ATTACH 'autre.duckdb' AS autre",
    "INSTALL httpfs",
    "SELECT 1; DROP TABLE t",  # requête de lecture suivie d'une écriture -- refusée dans son ensemble
])
def test_ensure_read_only_rejects_write_or_schema_queries(sql):
    with pytest.raises(ValueError):
        _ensure_read_only(sql)


def test_execute_query_refuses_write_without_touching_the_database(tmp_path, monkeypatch):
    # execute_query() ne doit même pas ouvrir de connexion pour une requête
    # refusée -- on vérifie ici que le message renvoyé est explicite et
    # qu'aucune exception ne remonte (comportement cohérent avec le message
    # "Erreur SQL: ..." déjà renvoyé pour un vrai échec SQL).
    result = execute_query("DROP TABLE some_table")
    assert result.startswith("Requête refusée :")


def test_execute_query_runs_a_real_read_query(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.duckdb")
    monkeypatch.setattr("mcp_server.server.db_path", db_path)
    result = execute_query("SELECT 1 AS un")
    assert "un" in result
    assert "1" in result


def test_health_check_reports_healthy(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.duckdb")
    monkeypatch.setattr("mcp_server.server.db_path", db_path)
    result = health_check()
    assert result["status"] == "healthy"
