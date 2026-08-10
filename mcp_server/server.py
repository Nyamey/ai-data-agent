# mcp_server/server.py — Serveur MCP pour DuckDB
"""
Ce serveur MCP expose DuckDB aux assistants IA compatibles MCP.
Une fois configuré, Claude Desktop ou VS Code peut interroger
directement ta base de données DuckDB.
"""
import os
import json
import re
from pathlib import Path
from mcp.server.mcpserver import MCPServer
import duckdb
from dotenv import load_dotenv

from agent.tools.data_loader import quote_ident

load_dotenv()

# execute_query() est exposée à des assistants IA externes (Claude Desktop,
# VS Code Copilot...) -- un outil d'exploration de données n'a aucune raison
# de permettre l'écriture ou la modification de schéma depuis ce canal-là
# (DROP/CREATE une table, ATTACH un autre fichier arbitraire du disque,
# INSTALL/LOAD une extension...). Une regex sur les mots-clés est une
# défense en profondeur simple, pas un vrai parseur SQL : suffisante pour
# empêcher un usage naïf ou un assistant mal aiguillé, pas un contournement
# volontaire et sophistiqué -- dans ce cas, la vraie protection reste de ne
# jamais exposer ce serveur à un client non fiable.
_DISALLOWED_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|ATTACH|DETACH|COPY|EXPORT|"
    r"IMPORT|CALL|PRAGMA|INSTALL|LOAD|SET|VACUUM|CHECKPOINT)\b",
    re.IGNORECASE,
)
_READ_ONLY_START = re.compile(r"^\s*(SELECT|WITH|DESCRIBE|SHOW|EXPLAIN)\b", re.IGNORECASE)


def _ensure_read_only(sql: str) -> None:
    """Lève ValueError si `sql` n'est pas une simple requête de lecture.

    Deux vérifications : une seule instruction (pas de `;` -- empêche
    d'enchaîner une requête de lecture anodine avec une écriture cachée
    derrière), et un mot-clé de départ appartenant à l'ensemble lecture
    seule. `_DISALLOWED_KEYWORDS` couvre en plus les cas où un mot-clé
    d'écriture apparaîtrait ailleurs que via un `;` (ex. dans une CTE).
    """
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        raise ValueError("Une seule instruction SQL est autorisée par appel.")
    if not _READ_ONLY_START.match(stripped):
        raise ValueError(
            "Seules les requêtes en lecture (SELECT/WITH/DESCRIBE/SHOW/EXPLAIN) sont autorisées."
        )
    if _DISALLOWED_KEYWORDS.search(stripped):
        raise ValueError(
            "Cette requête contient une opération d'écriture ou de modification de schéma, refusée."
        )

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
    Exécute une requête de LECTURE SQL sur DuckDB et retourne les résultats.

    Restreinte au lecture seule (SELECT/WITH/DESCRIBE/SHOW/EXPLAIN, une
    seule instruction) -- voir _ensure_read_only(). Ce serveur expose DuckDB
    à des assistants IA externes ; leur permettre d'écrire ou de modifier le
    schéma depuis un outil d'exploration de données n'a pas sa place ici.

    Args:
        sql: Requête SQL à exécuter (lecture seule)
        limit: Nombre maximum de lignes à retourner (défaut: 1000)

    Returns:
        Résultats formatés en tableau markdown
    """
    try:
        _ensure_read_only(sql)
    except ValueError as e:
        return f"Requête refusée : {e}"

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
    table_ref = quote_ident(table_name)
    con = get_connection()
    try:
        # file_path en paramètre lié (pas interpolé) : un chemin contenant
        # une apostrophe casserait sinon hors du littéral SQL et pourrait
        # injecter des instructions arbitraires -- même défaut que celui
        # trouvé et corrigé dans agent/tools/data_loader.py et
        # agent/streaming/pipeline.py.
        con.execute(
            f"CREATE OR REPLACE TABLE {table_ref} AS SELECT * FROM read_csv_auto(?, header=true)",
            [file_path],
        )
        count = con.execute(f"SELECT COUNT(*) FROM {table_ref}").fetchone()[0]
        cols = con.execute(f"DESCRIBE {table_ref}").fetchall()
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
        schema = con.execute(f"DESCRIBE {quote_ident(table_name)}").fetchdf()
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
    table_ref = quote_ident(table_name)
    con = get_connection()
    try:
        total = con.execute(f"SELECT COUNT(*) FROM {table_ref}").fetchone()[0]

        dups = con.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT *, COUNT(*) as cnt FROM {table_ref}
                GROUP BY ALL HAVING cnt > 1
            )
        """).fetchone()[0]

        schema = con.execute(f"DESCRIBE {table_ref}").fetchall()
        stats = []

        for col_name, col_type, *_ in schema:
            col_ref = quote_ident(col_name)
            nulls = con.execute(
                f"SELECT COUNT(*) FROM {table_ref} WHERE {col_ref} IS NULL"
            ).fetchone()[0]

            stat = {"colonne": col_name, "type": col_type, "valeurs_manquantes": nulls}

            # Statistiques numériques si applicable
            if any(t in col_type.upper() for t in ["INT", "DOUBLE", "FLOAT", "DECIMAL"]):
                result = con.execute(f"""
                    SELECT MIN({col_ref}), MAX({col_ref}), AVG({col_ref}),
                           MEDIAN({col_ref}), STDDEV({col_ref})
                    FROM {table_ref}
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
