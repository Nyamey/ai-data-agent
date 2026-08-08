# agent/nodes/test.py — Nœud 4 : Tests des facteurs explicatifs
from agent.state import AgentState, AnalysisStatus
from agent.tools.data_loader import execute_query


def test_node(state: AgentState) -> dict:
    """
    Nœud 4 : Test.
    
    Compare la rétention selon différents facteurs :
    plateforme, version d'app, crashes, engagement email, segment, région.
    """
    state.status = AnalysisStatus.TESTING
    
    table = state.data_metadata.get("table_name", "data")
    
    # Lister les colonnes disponibles
    columns = [s["column_name"] for s in state.data_metadata.get("schema", [])]
    
    # Pour chaque colonne catégorielle, calculer la rétention par segment
    driver_results = []
    
    # Essayer de comparer par les colonnes qui ressemblent à des dimensions
    dimension_cols = [
        col for col in columns 
        if col not in ["customer_id", "activity_date", "signup_date"]
        and "date" not in col.lower()
    ]
    
    for col in dimension_cols[:6]:  # Limiter à 6 colonnes
        try:
            query = f"""
                SELECT {col}, COUNT(DISTINCT customer_id) as nb_clients
                FROM {table}
                GROUP BY {col}
                ORDER BY nb_clients DESC
            """
            result = execute_query(query)
            driver_results.append({"dimension": col, "result": result})
        except Exception as e:
            driver_results.append({"dimension": col, "error": str(e)})
    
    return {
        "status": AnalysisStatus.VALIDATING,
        "driver_analysis": driver_results,
        "audit_trail": state.audit_trail + [f"Test : {len(driver_results)} dimensions analysées"],
    }
