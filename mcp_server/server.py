# mcp_server/server.py — Serveur MCP pour DuckDB
"""
Ce serveur MCP expose DuckDB aux assistants IA compatibles MCP.
Une fois configuré, Claude Desktop ou VS Code peut interroger
directement ta base de données DuckDB.
"""
import os
import json
from pathlib import Path
from mcp.server.mcpserver import MCPServer
import duckdb
from dotenv import load_dotenv

load_dotenv()

# Initialiser le serveur MCP
mcp = MCPServer(
    name="duckdb-analytics",
    version="1.0.0",
    description="Serveur d'analyse de données DuckDB pour agents IA",
)

# Connexion DuckDB
db_path = os.getenv("DUCKDB_PATH", "./data/analytics.duckdb")
Path(db_path).parent.mkdir(parents=True, exist_ok=True)


def get_connection():
    """
    Ouvre une connexion DuckDB à la demande.

    DuckDB verrouille le fichier tant qu'une connexion reste ouverte,
    donc on n'en garde jamais une active entre deux appels d'outil :
    ça bloquerait les autres processus (ex. le pipeline de streaming)
    qui accèdent au même fichier .duckdb.
    """
    return duckdb.connect(db_path)


@mcp.tool()
def health_check() -> dict:
    """Vérifie l'état du serveur DuckDB."""
    con = get_connection()
    try:
        result = con.execute("SELECT 1 as healthy").fetchone()
        version = con.execute("SELECT version()").fetchone()[0]
        tables = con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
        return {
            "status": "healthy" if result[0] == 1 else "unhealthy",
            "duckdb_version": version,
            "tables": [t[0] for t in tables],
        }
    finally:
        con.close()


@mcp.tool()
def execute_query(sql: str, limit: int = 1000) -> str:
    """
    Exécute une requête SQL sur DuckDB et retourne les résultats.
    
    Args:
        sql: Requête SQL à exécuter
        limit: Nombre maximum de lignes à retourner (défaut: 1000)
    
    Returns:
        Résultats formatés en tableau markdown
    """
    con = get_connection()
    try:
        df = con.execute(sql).fetchdf()
        if len(df) > limit:
            df = df.head(limit)
        return df.to_markdown(index=False)
    except Exception as e:
        return f"Erreur SQL: {e}"
    finally:
        con.close()


@mcp.tool()
def load_csv(file_path: str, table_name: str = None) -> str:
    """
    Charge un fichier CSV dans DuckDB.
    
    Args:
        file_path: Chemin vers le fichier CSV
        table_name: Nom de la table (défaut: nom du fichier)
    
    Returns:
        Message de confirmation avec le nombre de lignes chargées
    """
    table_name = table_name or Path(file_path).stem.replace("-", "_").replace(".", "_")
    con = get_connection()
    try:
        con.execute(f"""
            CREATE OR REPLACE TABLE {table_name} AS
            SELECT * FROM read_csv_auto('{file_path}', header=true)
        """)
        count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        cols = con.execute(f"DESCRIBE {table_name}").fetchall()
        return f"Table '{table_name}' chargée : {count} lignes, {len(cols)} colonnes"
    finally:
        con.close()


@mcp.tool()
def get_schema(table_name: str) -> str:
    """
    Retourne le schéma d'une table (noms et types de colonnes).
    
    Args:
        table_name: Nom de la table
    """
    con = get_connection()
    try:
        schema = con.execute(f"DESCRIBE {table_name}").fetchdf()
        return schema.to_markdown(index=False)
    finally:
        con.close()


@mcp.tool()
def profile_table(table_name: str) -> str:
    """
    Profile une table : statistiques descriptives, valeurs manquantes, doublons.
    
    Args:
        table_name: Nom de la table à profiler
    """
    con = get_connection()
    try:
        total = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

        dups = con.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT *, COUNT(*) as cnt FROM {table_name}
                GROUP BY ALL HAVING cnt > 1
            )
        """).fetchone()[0]

        schema = con.execute(f"DESCRIBE {table_name}").fetchall()
        stats = []

        for col_name, col_type, *_ in schema:
            nulls = con.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE {col_name} IS NULL"
            ).fetchone()[0]

            stat = {"colonne": col_name, "type": col_type, "valeurs_manquantes": nulls}

            # Statistiques numériques si applicable
            if any(t in col_type.upper() for t in ["INT", "DOUBLE", "FLOAT", "DECIMAL"]):
                result = con.execute(f"""
                    SELECT MIN({col_name}), MAX({col_name}), AVG({col_name}),
                           MEDIAN({col_name}), STDDEV({col_name})
                    FROM {table_name}
                """).fetchone()
                stat.update({
                    "min": result[0], "max": result[1], "moyenne": result[2],
                    "mediane": result[3], "ecart_type": result[4],
                })

            stats.append(stat)

        return json.dumps({
            "total_lignes": total,
            "doublons": dups,
            "profiling": stats,
        }, indent=2, default=str)
    finally:
        con.close()


if __name__ == "__main__":
    mcp.run()
