# agent/nodes/build.py : nœud 3, construction des analyses
from agent.state import AgentState, AnalysisStatus
from agent.tools.data_loader import execute_query, quote_ident


def build_node(state: AgentState) -> dict:
    """
    Nœud 3 : Construction.

    Calcule une métrique agrégée sur DuckDB. Agnostique au schéma : si une
    colonne de date existe, la métrique est suivie dans le temps (par
    semaine) ; si une colonne d'identifiant d'entité est détectée
    (ex. customer_id), on compte les entités distinctes, sinon le nombre
    de lignes.
    """
    state.status = AnalysisStatus.BUILDING

    # table/id_col/date_col viennent tous du schéma du CSV téléversé (non
    # fiable) : quote_ident() est requis à chaque interpolation SQL, pas une
    # précaution superflue, voir sa docstring dans agent/tools/data_loader.py.
    table = quote_ident(state.data_metadata.get("table_name", "data"))
    db_path = state.data_metadata.get("db_path")
    id_col = state.data_metadata.get("id_column")
    date_cols = list(state.data_metadata.get("date_range", {}).keys())
    date_col = date_cols[0] if date_cols else None

    count_expr = f"COUNT(DISTINCT {quote_ident(id_col)})" if id_col else "COUNT(*)"
    count_label = "entités distinctes" if id_col else "lignes"

    if date_col:
        query = f"""
            SELECT
                DATE_TRUNC('week', {quote_ident(date_col)}) as semaine,
                {count_expr} as valeur
            FROM {table}
            GROUP BY 1
            ORDER BY 1
        """
        label = f"Évolution hebdomadaire ({count_label}, sur {date_col})"
    else:
        query = f"SELECT {count_expr} as valeur FROM {table}"
        label = f"Total ({count_label}), aucune colonne date détectée"

    # execute_query() absorbe déjà ses propres exceptions (renvoie une
    # chaîne "Erreur SQL: ..." au lieu de lever) : un try/except ici ne
    # s'exécuterait jamais.
    result = execute_query(query, db_path=db_path)

    return {
        "status": AnalysisStatus.TESTING,
        # "query" est conservée pour que l'étape d'export puisse ré-exécuter
        # le même calcul sous forme de DataFrame (execute_query ne renvoie
        # que du markdown, impropre à la génération Excel/PPTX).
        "weekly_retention": {"data": result, "label": label, "query": query},
        "audit_trail": state.audit_trail + [f"Construction : {label.lower()} calculée"],
    }
