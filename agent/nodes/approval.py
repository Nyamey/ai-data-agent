# agent/nodes/approval.py — Point de contrôle humain
from agent.state import AgentState, AnalysisStatus


def approval_check_node(state: AgentState) -> dict:
    """
    Point de contrôle : attend l'approbation humaine après l'inspection.
    
    Affiche un résumé de ce qui a été trouvé et demande à l'utilisateur
    s'il souhaite continuer.
    """
    print("\n" + "=" * 60)
    print("RÉSUMÉ DE L'INSPECTION — APPROBATION REQUISE")
    print("=" * 60)
    print(f"\nQuestion : {state.business_question}")
    print(f"Métrique : {state.metric_definition}")
    print(f"Période : {state.comparison_period}")
    print(f"\nDonnées : {state.data_path}")
    
    if state.data_metadata:
        meta = state.data_metadata
        print(f"  - Lignes : {meta['row_count']}")
        print(f"  - Colonnes : {len(meta['schema'])}")
        print(f"  - Doublons : {meta['duplicate_count']}")
        print(f"  - Valeurs manquantes : {meta['null_counts']}")
        print(f"  - Plage de dates : {meta['date_range']}")
    
    print(f"\nAgrégation nécessaire : {'Oui' if state.needs_aggregation else 'Non'}")
    print(f"Hypothèses : {state.assumptions}")
    print("\n" + "=" * 60)
    
    # Demander l'approbation
    approval = input("\nApprouvez-vous la poursuite de l'analyse ? (oui/non) : ")
    
    if approval.lower() in ["oui", "o", "yes", "y"]:
        return {
            "status": AnalysisStatus.BUILDING,
            "approval_received": True,
            "audit_trail": state.audit_trail + ["Approbation reçue de l'utilisateur"],
        }
    else:
        return {
            "status": AnalysisStatus.FAILED,
            "errors": state.errors + ["Analyse rejetée par l'utilisateur"],
        }
