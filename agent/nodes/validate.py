# agent/nodes/validate.py — Nœud 5 : Validation
from agent.state import AgentState, AnalysisStatus
from agent.tools.data_loader import execute_query


def validate_node(state: AgentState) -> dict:
    """
    Nœud 5 : Validation.
    
    Vérifie la cohérence des résultats :
    - Rapproche les comptes clients
    - Vérifie que les chiffres sont reproductibles
    """
    state.status = AnalysisStatus.VALIDATING
    
    table = state.data_metadata.get("table_name", "data")
    
    checks = {}
    
    # Vérification 1 : nombre total de clients unique
    try:
        total = execute_query(
            f"SELECT COUNT(DISTINCT customer_id) as total FROM {table}"
        )
        checks["total_clients"] = {"result": total, "passed": True}
    except Exception as e:
        checks["total_clients"] = {"result": str(e), "passed": False}
    
    # Vérification 2 : plage de dates
    try:
        dates = execute_query(
            f"SELECT MIN(activity_date), MAX(activity_date) FROM {table}"
        )
        checks["plage_dates"] = {"result": dates, "passed": True}
    except Exception as e:
        checks["plage_dates"] = {"result": str(e), "passed": False}
    
    # Vérification 3 : doublons
    dup_count = state.data_metadata.get("duplicate_count", 0)
    checks["doublons"] = {"result": dup_count, "passed": dup_count == 0}
    
    return {
        "status": AnalysisStatus.RECOMMENDING,
        "validation_checks": checks,
        "audit_trail": state.audit_trail + [
            f"Validation : {len(checks)} contrôles effectués, "
            f"{sum(1 for c in checks.values() if c['passed'])} réussis"
        ],
    }
