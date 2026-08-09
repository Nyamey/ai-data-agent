# agent/nodes/test.py — Nœud 4 : Tests des facteurs explicatifs
from agent.state import AgentState, AnalysisStatus
from agent.tools.data_loader import execute_query


def test_node(state: AgentState) -> dict:
    """
    Nœud 4 : Test.

    Compare la métrique selon les colonnes catégorielles disponibles
    (ex. plateforme, région, segment...). Agnostique au schéma : les
    colonnes exclues (identifiant d'entité, dates) sont celles détectées
    par l'inspection, pas des noms fixes.
    """
    state.status = AnalysisStatus.TESTING

    table = state.data_metadata.get("table_name", "data")
    db_path = state.data_metadata.get("db_path")
    id_col = state.data_metadata.get("id_column")
    date_cols = set(state.data_metadata.get("date_range", {}).keys())

    count_expr = f"COUNT(DISTINCT {id_col})" if id_col else "COUNT(*)"
    count_label = "nb_entites" if id_col else "nb_lignes"

    # Lister les colonnes disponibles
    columns = [s["column_name"] for s in state.data_metadata.get("schema", [])]

    # Pour chaque colonne catégorielle, calculer la métrique par segment
    driver_results = []

    excluded = date_cols | ({id_col} if id_col else set())
    dimension_cols = [
        col for col in columns
        if col not in excluded and "date" not in col.lower()
    ]

    for col in dimension_cols[:6]:  # Limiter à 6 colonnes
        try:
            query = f"""
                SELECT {col}, {count_expr} as {count_label}
                FROM {table}
                GROUP BY {col}
                ORDER BY {count_label} DESC
            """
            result = execute_query(query, db_path=db_path)
            driver_results.append({"dimension": col, "result": result})
        except Exception as e:
            driver_results.append({"dimension": col, "error": str(e)})

    return {
        "status": AnalysisStatus.VALIDATING,
        "driver_analysis": driver_results,
        "audit_trail": state.audit_trail + [f"Test : {len(driver_results)} dimensions analysées"],
    }
