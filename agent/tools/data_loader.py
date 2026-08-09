# agent/tools/data_loader.py — Chargement et inspection de données avec DuckDB
import re
import duckdb
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ID_COLUMN_PATTERN = re.compile(r"(^id$)|(_id$)|(^id_)", re.IGNORECASE)

# Caractères sans risque dans un nom de table (le nom de fichier téléversé
# passe par ici) : au-delà des tirets/points déjà neutralisés par le seul
# .replace() historique, tout le reste doit être neutralisé aussi.
UNSAFE_TABLE_CHARS = re.compile(r"[^A-Za-z0-9_]")


def quote_ident(name: str) -> str:
    """Échappe un identifiant SQL (nom de colonne ou de table) pour DuckDB.

    Les noms de colonnes viennent tels quels de l'en-tête du CSV téléversé
    par l'utilisateur -- une donnée non fiable. Sans ce guillemetage, un nom
    de colonne comme `1) UNION SELECT secret FROM autre_table -- x_id`
    (qui matche en plus ID_COLUMN_PATTERN via son suffixe `_id`) sort du
    contexte d'identifiant et injecte du SQL arbitraire dans les requêtes
    de build_node/test_node/validate_node, jusqu'à lire des tables DuckDB
    sans rapport -- confirmé par test manuel avant ce correctif. Mettre le
    nom entre guillemets doubles (en doublant les guillemets internes) le
    neutralise complètement : DuckDB traite alors tout le contenu comme un
    simple nom, jamais comme du SQL.
    """
    return '"' + str(name).replace('"', '""') + '"'


def detect_id_column(schema: list[dict], date_columns: list[str]) -> str | None:
    """
    Devine la colonne qui identifie une entité (ex. customer_id), pour
    généraliser les métriques ("nombre d'entités distinctes") à un CSV
    quelconque plutôt que de supposer un nom de colonne fixe.

    Heuristique : première colonne dont le nom matche id/_id/id_, en
    excluant les colonnes de date. À défaut, aucune colonne n'est
    retenue et les métriques retombent sur un simple COUNT(*).
    """
    for s in schema:
        col = s["column_name"]
        if col in date_columns:
            continue
        if ID_COLUMN_PATTERN.search(col):
            return col
    return None


def _table_name_from_path(csv_path: str) -> str:
    """Dérive un nom de table sûr à partir d'un chemin de fichier.

    Tout caractère qui n'est pas alphanumérique/underscore est neutralisé --
    voir UNSAFE_TABLE_CHARS.
    """
    return UNSAFE_TABLE_CHARS.sub("_", Path(csv_path).stem)


def _load_csv_into_table(con, csv_path: str) -> str:
    """Charge un CSV dans sa propre table DuckDB et retourne son nom.

    Factorisé hors de load_data()/load_joined_data() : les deux ont besoin
    de charger un ou plusieurs CSV de la même façon avant de calculer des
    métadonnées différentes (une seule table vs une jointure).
    """
    table_name = _table_name_from_path(csv_path)
    con.execute(f"""
        CREATE OR REPLACE TABLE {quote_ident(table_name)} AS
        SELECT * FROM read_csv_auto('{csv_path}', header=true)
    """)
    return table_name


def _extract_table_metadata(con, table_name: str) -> dict:
    """Calcule les métadonnées d'inspection d'une table déjà chargée.

    Commun à load_data() (une table = un CSV) et load_joined_data() (une
    table = plusieurs CSV joints) : une fois la table en place, l'inspection
    (schéma, plage de dates, valeurs manquantes, doublons, colonne
    identifiant) ne dépend pas de son origine.
    """
    table_ref = quote_ident(table_name)

    # Récupérer le schéma (noms et types de colonnes)
    schema = con.execute(f"DESCRIBE {table_ref}").fetchdf().to_dict(orient="records")

    # Compter les lignes
    row_count = con.execute(f"SELECT COUNT(*) FROM {table_ref}").fetchone()[0]

    # Détecter les colonnes de date
    date_columns = [
        s["column_name"] for s in schema
        if "date" in s["column_type"].lower() or "timestamp" in s["column_type"].lower()
    ]

    # Plage de dates pour chaque colonne de date. Les noms de colonnes
    # viennent du CSV téléversé (non fiable) : quote_ident() est
    # indispensable ici, pas une précaution superflue -- voir sa docstring.
    date_range = {}
    for col in date_columns:
        result = con.execute(f"""
            SELECT MIN({quote_ident(col)}) as min_date, MAX({quote_ident(col)}) as max_date
            FROM {table_ref}
        """).fetchone()
        date_range[col] = {"min": str(result[0]), "max": str(result[1])}

    # Compter les valeurs manquantes par colonne
    null_counts = {}
    for s in schema:
        col = s["column_name"]
        null_count = con.execute(f"""
            SELECT COUNT(*) FROM {table_ref} WHERE {quote_ident(col)} IS NULL
        """).fetchone()[0]
        if null_count > 0:
            null_counts[col] = null_count

    # Détecter les doublons
    duplicate_count = con.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT *, COUNT(*) as cnt
            FROM {table_ref}
            GROUP BY ALL
            HAVING cnt > 1
        )
    """).fetchone()[0]

    id_column = detect_id_column(schema, date_columns)

    return {
        "schema": schema,
        "row_count": row_count,
        "date_range": date_range,
        "null_counts": null_counts,
        "duplicate_count": duplicate_count,
        "id_column": id_column,
    }


def load_data(csv_path: str, db_path: str = None) -> dict:
    """
    Charge un fichier CSV dans DuckDB et retourne les métadonnées.

    Args:
        csv_path: Chemin vers le fichier CSV
        db_path: Chemin vers la base DuckDB (optionnel)

    Returns:
        Dictionnaire avec le schéma, nombre de lignes, valeurs manquantes, etc.
    """
    db_path = db_path or os.getenv("DUCKDB_PATH", "./data/analytics.duckdb")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(db_path)

    table_name = _load_csv_into_table(con, csv_path)
    metadata = _extract_table_metadata(con, table_name)
    con.close()

    return {
        "table_name": table_name,
        # Chemin DuckDB effectivement utilisé (résolu depuis l'argument ou
        # DUCKDB_PATH) -- propagé aux nœuds suivants pour qu'ils interrogent
        # la même base, y compris quand un chemin par session est utilisé.
        "db_path": db_path,
        **metadata,
    }


def load_joined_data(csv_paths: list[str], join_spec: dict, db_path: str = None) -> dict:
    """
    Charge plusieurs CSV dans DuckDB et les joint en une seule table, pour
    une analyse croisée (ex. commandes + clients + produits).

    join_spec décrit un arbre de jointure construit incrémentalement par
    l'utilisateur (pas de détection automatique de clé, trop fragile) :
        {
            "root": "commandes.csv",
            "joins": [
                {"file": "clients.csv", "on_file": "commandes.csv",
                 "file_column": "id", "on_column": "client_id", "how": "inner"},
                {"file": "produits.csv", "on_file": "commandes.csv",
                 "file_column": "id", "on_column": "produit_id", "how": "inner"},
            ],
        }
    Chaque étape doit se rattacher à un fichier déjà inclus (root ou une
    étape précédente) -- ça garantit un arbre connexe plutôt qu'un graphe de
    jointures ambigu, tout en couvrant un nombre quelconque de fichiers.

    Toutes les colonnes de sortie sont préfixées "{table}__{colonne}" pour
    éviter toute collision entre fichiers (ex. deux fichiers avec une
    colonne "date" ou "id") -- la détection de colonne identifiant/date en
    aval fonctionne aussi bien sur ces noms préfixés.

    Comme il n'y a pas de détection automatique de clé, rien ne garantit que
    les colonnes choisies par l'utilisateur se correspondent réellement --
    joindre sur des colonnes sans rapport produit silencieusement une table
    vide (aucune valeur en commun) ou, à l'inverse, une explosion du nombre
    de lignes (colonne choisie non unique). Ces deux cas sont détectés après
    coup en comparant le nombre de lignes obtenu à celui de chaque fichier
    source, et exposés via metadata["join_warning"] (None si rien d'anormal)
    -- affiché dans le résumé d'approbation et dans l'interface Streamlit
    pour que l'utilisateur puisse corriger sa configuration avant de
    poursuivre une analyse qui ne veut rien dire.

    Returns:
        Même forme que load_data(), plus "source_files" (chemins d'origine),
        "source_row_counts" (nombre de lignes de chaque fichier avant
        jointure) et "join_warning" (message si le résultat semble anormal).
    """
    db_path = db_path or os.getenv("DUCKDB_PATH", "./data/analytics.duckdb")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(db_path)

    table_by_path = {path: _load_csv_into_table(con, path) for path in csv_paths}
    source_row_counts = {
        path: con.execute(f"SELECT COUNT(*) FROM {quote_ident(table)}").fetchone()[0]
        for path, table in table_by_path.items()
    }

    root_path = join_spec["root"]
    if root_path not in table_by_path:
        raise ValueError(f"Fichier racine '{root_path}' absent de csv_paths.")

    from_clause = quote_ident(table_by_path[root_path])
    included = {root_path}
    for step in join_spec.get("joins", []):
        file_path, on_path = step["file"], step["on_file"]
        if on_path not in included:
            raise ValueError(
                f"'{on_path}' doit être ajouté avant '{file_path}' dans join_spec['joins']."
            )
        how = step.get("how", "inner").upper()
        if how not in ("INNER", "LEFT"):
            raise ValueError(f"Type de jointure non supporté : {how}")
        from_clause += (
            f"\n{how} JOIN {quote_ident(table_by_path[file_path])}"
            f" ON {quote_ident(table_by_path[on_path])}.{quote_ident(step['on_column'])}"
            f" = {quote_ident(table_by_path[file_path])}.{quote_ident(step['file_column'])}"
        )
        included.add(file_path)

    # Sélectionner et préfixer les colonnes de chaque table pour construire
    # la table jointe finale.
    select_parts = []
    for path in csv_paths:
        table = table_by_path[path]
        columns = con.execute(f"DESCRIBE {quote_ident(table)}").fetchdf()["column_name"].tolist()
        for col in columns:
            alias = f"{table}__{col}"
            select_parts.append(f"{quote_ident(table)}.{quote_ident(col)} AS {quote_ident(alias)}")

    joined_table = _table_name_from_path("joined_" + "_".join(table_by_path.values()))[:63]
    con.execute(f"""
        CREATE OR REPLACE TABLE {quote_ident(joined_table)} AS
        SELECT {', '.join(select_parts)}
        FROM {from_clause}
    """)

    metadata = _extract_table_metadata(con, joined_table)
    con.close()

    return {
        "table_name": joined_table,
        "db_path": db_path,
        "source_files": csv_paths,
        "source_row_counts": source_row_counts,
        "join_warning": _diagnose_join(metadata["row_count"], source_row_counts),
        **metadata,
    }


def _diagnose_join(row_count: int, source_row_counts: dict) -> str | None:
    """Détecte une jointure qui a probablement échoué (aucune vraie clé commune).

    Deux symptômes couvrent la grande majorité des configurations
    incorrectes, sans avoir besoin de connaître les vraies clés :
    - 0 ligne en sortie : aucune valeur en commun entre les colonnes choisies.
    - Beaucoup plus de lignes qu'aucun fichier source : la colonne choisie
      n'est pas unique côté "on_column", chaque correspondance se multiplie
      (produit cartésien partiel).
    """
    if not source_row_counts:
        return None
    max_source = max(source_row_counts.values())

    if row_count == 0:
        return (
            "La jointure ne produit aucune ligne : les colonnes choisies ne "
            "semblent avoir aucune valeur en commun entre les fichiers. "
            "Vérifiez qu'il s'agit bien d'une clé partagée (ex. un même "
            "identifiant client), pas de deux colonnes sans rapport."
        )
    if max_source > 0 and row_count > 3 * max_source:
        return (
            f"La jointure produit beaucoup plus de lignes ({row_count}) que le "
            f"plus grand fichier source ({max_source}) : la colonne choisie "
            "n'est probablement pas unique, ce qui multiplie les correspondances "
            "au lieu de les croiser proprement."
        )
    return None


def fetch_dataframe(sql: str, db_path: str = None):
    """
    Exécute une requête SQL sur DuckDB et retourne un DataFrame brut.

    Contrairement à execute_query() (pensé pour l'affichage/le LLM, qui
    renvoie du markdown), cette fonction sert quand le résultat doit être
    manipulé par du code -- tests statistiques, export Excel/PPTX...

    Args:
        sql: Requête SQL à exécuter
        db_path: Chemin vers la base DuckDB

    Returns:
        pandas.DataFrame
    """
    db_path = db_path or os.getenv("DUCKDB_PATH", "./data/analytics.duckdb")
    con = duckdb.connect(db_path)
    try:
        return con.execute(sql).fetchdf()
    finally:
        con.close()


def execute_query(sql: str, db_path: str = None) -> str:
    """
    Exécute une requête SQL sur DuckDB et retourne le résultat en markdown.

    Args:
        sql: Requête SQL à exécuter
        db_path: Chemin vers la base DuckDB

    Returns:
        Résultat formaté en tableau markdown
    """
    try:
        return fetch_dataframe(sql, db_path=db_path).to_markdown(index=False)
    except Exception as e:
        return f"Erreur SQL: {e}"
