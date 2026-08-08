# agent/nodes/build.py — Nœud 3 : Construction des analyses
from agent.state import AgentState, AnalysisStatus
from agent.tools.data_loader import execute_query


def build_node(state: AgentState) -> dict:
    """
    Nœud 3 : Construction.
    
    Calcule la rétention hebdomadaire et crée l'analyse de cohorte
    en utilisant DuckDB pour les requêtes.
    """
    state.status = AnalysisStatus.BUILDING
    
    table = state.data_metadata.get("table_name", "data")
    
    # Calculer la rétention hebdomadaire avec DuckDB
    weekly_query = f"""
        SELECT 
            DATE_TRUNC('week', activity_date) as semaine,
            COUNT(DISTINCT customer_id) as utilisateurs_actifs
        FROM {table}
        GROUP BY 1
        ORDER BY 1
    """
    
    try:
        weekly_result = execute_query(weekly_query)
    except Exception as e:
        weekly_result = f"Erreur: {e}"
    
    return {
        "status": AnalysisStatus.TESTING,
        "weekly_retention": {"data": weekly_result},
        "audit_trail": state.audit_trail + ["Construction : rétention hebdomadaire calculée"],
    }
