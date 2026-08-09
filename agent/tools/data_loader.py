# agent/tools/data_loader.py — Chargement et inspection de données avec DuckDB
import re
import duckdb
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ID_COLUMN_PATTERN = re.compile(r"(^id$)|(_id$)|(^id_)", re.IGNORECASE)


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
    
    # S'assurer que le dossier existe
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Connexion à DuckDB
    con = duckdb.connect(db_path)
    
    # Nom de table à partir du nom de fichier
    table_name = Path(csv_path).stem.replace("-", "_").replace(".", "_")
    
    # Charger le CSV dans DuckDB (lecture automatique des types)
    con.execute(f"""
        CREATE OR REPLACE TABLE {table_name} AS 
        SELECT * FROM read_csv_auto('{csv_path}', header=true)
    """)
    
    # Récupérer le schéma (noms et types de colonnes)
    schema = con.execute(f"DESCRIBE {table_name}").fetchdf().to_dict(orient="records")
    
    # Compter les lignes
    row_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    
    # Détecter les colonnes de date
    date_columns = [
        s["column_name"] for s in schema 
        if "date" in s["column_type"].lower() or "timestamp" in s["column_type"].lower()
    ]
    
    # Plage de dates pour chaque colonne de date
    date_range = {}
    for col in date_columns:
        result = con.execute(f"""
            SELECT MIN({col}) as min_date, MAX({col}) as max_date 
            FROM {table_name}
        """).fetchone()
        date_range[col] = {"min": str(result[0]), "max": str(result[1])}
    
    # Compter les valeurs manquantes par colonne
    null_counts = {}
    for s in schema:
        col = s["column_name"]
        null_count = con.execute(f"""
            SELECT COUNT(*) FROM {table_name} WHERE {col} IS NULL
        """).fetchone()[0]
        if null_count > 0:
            null_counts[col] = null_count
    
    # Détecter les doublons
    duplicate_count = con.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT *, COUNT(*) as cnt 
            FROM {table_name} 
            GROUP BY ALL 
            HAVING cnt > 1
        )
    """).fetchone()[0]
    
    con.close()

    id_column = detect_id_column(schema, date_columns)

    return {
        "table_name": table_name,
        "schema": schema,
        "row_count": row_count,
        "date_range": date_range,
        "null_counts": null_counts,
        "duplicate_count": duplicate_count,
        "id_column": id_column,
        # Chemin DuckDB effectivement utilisé (résolu depuis l'argument ou
        # DUCKDB_PATH) -- propagé aux nœuds suivants pour qu'ils interrogent
        # la même base, y compris quand un chemin par session est utilisé.
        "db_path": db_path,
    }


def execute_query(sql: str, db_path: str = None) -> str:
    """
    Exécute une requête SQL sur DuckDB et retourne le résultat en markdown.
    
    Args:
        sql: Requête SQL à exécuter
        db_path: Chemin vers la base DuckDB
    
    Returns:
        Résultat formaté en tableau markdown
    """
    db_path = db_path or os.getenv("DUCKDB_PATH", "./data/analytics.duckdb")
    con = duckdb.connect(db_path)
    
    try:
        df = con.execute(sql).fetchdf()
        con.close()
        return df.to_markdown(index=False)
    except Exception as e:
        con.close()
        return f"Erreur SQL: {e}"
