# tests/test_data_loader.py — Chargement DuckDB et détection de schéma
import duckdb
import pandas as pd
import pytest

from agent.tools.data_loader import (
    _diagnose_join,
    detect_id_column,
    execute_query,
    fetch_dataframe,
    load_data,
    load_joined_data,
    quote_ident,
)


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


# --- load_joined_data() : analyse croisée entre plusieurs fichiers ---

def _three_way_join_spec(paths):
    return {
        "root": paths["commandes"],
        "joins": [
            {"file": paths["clients"], "on_file": paths["commandes"],
             "file_column": "id", "on_column": "client_id_ref", "how": "inner"},
            {"file": paths["produits"], "on_file": paths["commandes"],
             "file_column": "id", "on_column": "produit_id_ref", "how": "inner"},
        ],
    }


def test_load_joined_data_joins_three_files(sample_joinable_csvs, tmp_path):
    paths = sample_joinable_csvs
    db_path = str(tmp_path / "analytics.duckdb")
    meta = load_joined_data(
        [paths["commandes"], paths["clients"], paths["produits"]],
        _three_way_join_spec(paths),
        db_path=db_path,
    )

    assert meta["row_count"] == 40  # chaque commande a un client et un produit valides
    assert meta["source_files"] == [paths["commandes"], paths["clients"], paths["produits"]]
    columns = {s["column_name"] for s in meta["schema"]}
    # Toutes les colonnes sont préfixées par leur fichier d'origine
    assert "commandes__montant" in columns
    assert "clients__segment" in columns
    assert "produits__categorie" in columns


def test_load_joined_data_prefixes_avoid_column_collisions(sample_joinable_csvs, tmp_path):
    # commandes, clients et produits ont chacun leur propre colonne "id" --
    # sans préfixage ce serait une collision silencieuse.
    paths = sample_joinable_csvs
    db_path = str(tmp_path / "analytics.duckdb")
    meta = load_joined_data(
        [paths["commandes"], paths["clients"], paths["produits"]],
        _three_way_join_spec(paths),
        db_path=db_path,
    )
    columns = [s["column_name"] for s in meta["schema"]]
    assert columns.count("commandes__id") == 1
    assert columns.count("clients__id") == 1
    assert columns.count("produits__id") == 1


def test_load_joined_data_detects_id_and_date_on_joined_table(sample_joinable_csvs, tmp_path):
    paths = sample_joinable_csvs
    db_path = str(tmp_path / "analytics.duckdb")
    meta = load_joined_data(
        [paths["commandes"], paths["clients"], paths["produits"]],
        _three_way_join_spec(paths),
        db_path=db_path,
    )
    assert meta["id_column"] == "commandes__id"
    assert "commandes__date_commande" in meta["date_range"]


def test_load_joined_data_rejects_join_step_referencing_unincluded_file(sample_joinable_csvs, tmp_path):
    paths = sample_joinable_csvs
    bad_spec = {
        "root": paths["commandes"],
        "joins": [
            # "produits" avant "clients" alors que rien ne le référence encore
            {"file": paths["clients"], "on_file": paths["produits"],
             "file_column": "id", "on_column": "id", "how": "inner"},
        ],
    }
    with pytest.raises(ValueError):
        load_joined_data(
            [paths["commandes"], paths["clients"], paths["produits"]],
            bad_spec,
            db_path=str(tmp_path / "analytics.duckdb"),
        )


def test_load_joined_data_rejects_unsupported_join_type(sample_joinable_csvs, tmp_path):
    paths = sample_joinable_csvs
    bad_spec = {
        "root": paths["commandes"],
        "joins": [
            {"file": paths["clients"], "on_file": paths["commandes"],
             "file_column": "id", "on_column": "client_id_ref", "how": "full outer; DROP TABLE x"},
        ],
    }
    with pytest.raises(ValueError):
        load_joined_data(
            [paths["commandes"], paths["clients"]],
            bad_spec,
            db_path=str(tmp_path / "analytics.duckdb"),
        )


def test_load_joined_data_left_join_keeps_unmatched_rows(tmp_path):
    a = pd.DataFrame({"id": [1, 2, 3]})
    b = pd.DataFrame({"a_id": [1, 2], "label": ["x", "y"]})  # pas de correspondance pour id=3
    a_path, b_path = tmp_path / "a.csv", tmp_path / "b.csv"
    a.to_csv(a_path, index=False)
    b.to_csv(b_path, index=False)

    spec = {
        "root": str(a_path),
        "joins": [{"file": str(b_path), "on_file": str(a_path),
                   "file_column": "a_id", "on_column": "id", "how": "left"}],
    }
    meta_left = load_joined_data([str(a_path), str(b_path)], spec, db_path=str(tmp_path / "left.duckdb"))
    assert meta_left["row_count"] == 3  # id=3 conservé malgré l'absence de correspondance

    spec_inner = {**spec, "joins": [{**spec["joins"][0], "how": "inner"}]}
    meta_inner = load_joined_data([str(a_path), str(b_path)], spec_inner, db_path=str(tmp_path / "inner.duckdb"))
    assert meta_inner["row_count"] == 2  # id=3 exclu


def test_load_joined_data_neutralizes_malicious_column_name(tmp_path):
    # Même attaque que test_load_data_does_not_leak_data_via_malicious_column_name,
    # mais au travers du chemin de jointure (SELECT avec alias préfixé).
    evil_col = "1) as x FROM commandes UNION SELECT flag as x FROM secrets -- x_id"
    commandes = pd.DataFrame({"id": [1, 2], "client_id_ref": [1, 2]})
    clients = pd.DataFrame({"id": [1, 2], evil_col: [9, 9]})
    commandes_path, clients_path = tmp_path / "commandes.csv", tmp_path / "clients.csv"
    commandes.to_csv(commandes_path, index=False)
    clients.to_csv(clients_path, index=False)

    db_path = str(tmp_path / "analytics.duckdb")
    con = duckdb.connect(db_path)
    con.execute("CREATE TABLE secrets AS SELECT 'FUITE_DE_DONNEES' as flag")
    con.close()

    spec = {
        "root": str(commandes_path),
        "joins": [{"file": str(clients_path), "on_file": str(commandes_path),
                   "file_column": "id", "on_column": "client_id_ref", "how": "inner"}],
    }
    meta = load_joined_data([str(commandes_path), str(clients_path)], spec, db_path=db_path)
    assert meta["row_count"] == 2
    assert "FUITE_DE_DONNEES" not in str(meta["schema"])


def test_load_joined_data_supports_five_files(tmp_path):
    # MAX_FILES (app.py) autorise jusqu'à 5 fichiers en mode simple -- le
    # mode jointure doit supporter le même plafond, pas seulement 2 ou 3.
    root = pd.DataFrame({"id": range(1, 11)})
    paths = {"root": tmp_path / "f0.csv"}
    root.to_csv(paths["root"], index=False)

    join_steps = []
    for i in range(1, 5):
        df = pd.DataFrame({"ref": range(1, 11), f"valeur_{i}": range(10)})
        path = tmp_path / f"f{i}.csv"
        df.to_csv(path, index=False)
        paths[f"f{i}"] = path
        # Chacun se rattache à la racine (arbre en étoile) -- un cas limite
        # différent de la chaîne linéaire testée par ailleurs.
        join_steps.append({
            "file": str(path), "on_file": str(paths["root"]),
            "file_column": "ref", "on_column": "id", "how": "inner",
        })

    spec = {"root": str(paths["root"]), "joins": join_steps}
    all_paths = [str(paths["root"])] + [str(paths[f"f{i}"]) for i in range(1, 5)]
    meta = load_joined_data(all_paths, spec, db_path=str(tmp_path / "analytics.duckdb"))

    assert meta["row_count"] == 10
    columns = {s["column_name"] for s in meta["schema"]}
    for i in range(1, 5):
        assert f"f{i}__valeur_{i}" in columns


# --- Diagnostic post-jointure : détecte une jointure sur de mauvaises colonnes ---

def test_diagnose_join_flags_empty_result():
    warning = _diagnose_join(0, {"a.csv": 20, "b.csv": 15})
    assert warning is not None
    assert "aucune ligne" in warning


def test_diagnose_join_flags_cartesian_explosion():
    warning = _diagnose_join(500, {"a.csv": 20, "b.csv": 15})
    assert warning is not None
    assert "plus de lignes" in warning


def test_diagnose_join_silent_on_healthy_join():
    assert _diagnose_join(18, {"a.csv": 20, "b.csv": 15}) is None


def test_diagnose_join_silent_when_no_sources():
    assert _diagnose_join(0, {}) is None


def test_load_joined_data_warns_when_files_are_unrelated(tmp_path):
    # Reproduit le rapport utilisateur : 3 fichiers sans aucun rapport entre
    # eux, joints sur les colonnes par défaut (première colonne de chacun) --
    # la jointure ne doit pas échouer silencieusement.
    meteo = pd.DataFrame({"ville": ["Paris", "Lyon", "Marseille"] * 5, "temperature": range(15)})
    films = pd.DataFrame({"titre": [f"Film{i}" for i in range(10)], "genre": ["Action"] * 10})

    meteo_path, films_path = tmp_path / "meteo.csv", tmp_path / "films.csv"
    meteo.to_csv(meteo_path, index=False)
    films.to_csv(films_path, index=False)

    spec = {
        "root": str(meteo_path),
        "joins": [{"file": str(films_path), "on_file": str(meteo_path),
                   "file_column": "titre", "on_column": "ville", "how": "inner"}],
    }
    meta = load_joined_data([str(meteo_path), str(films_path)], spec, db_path=str(tmp_path / "analytics.duckdb"))

    assert meta["row_count"] == 0
    assert meta["source_row_counts"] == {str(meteo_path): 15, str(films_path): 10}
    assert meta["join_warning"] is not None
    assert "aucune ligne" in meta["join_warning"]


def test_load_joined_data_no_warning_on_legitimate_join(sample_joinable_csvs, tmp_path):
    paths = sample_joinable_csvs
    meta = load_joined_data(
        [paths["commandes"], paths["clients"], paths["produits"]],
        _three_way_join_spec(paths),
        db_path=str(tmp_path / "analytics.duckdb"),
    )
    assert meta["join_warning"] is None
