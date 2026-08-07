# agent/nodes/inspection.py — Nœud 2 : Inspection des données
from agent.state import AgentState, AnalysisStatus
from agent.tools.data_loader import load_data


def inspection_node(state: AgentState) -> dict:
    """
    Nœud 2 : Inspection des données.
    
    Vérifie automatiquement :
    - Le schéma (noms et types de colonnes)
    - Le nombre de lignes
    - La plage de dates
    - Les valeurs manquantes
    - Les doublons
    - Si une agrégation est nécessaire
    
    Ensuite, l'agent s'arrête pour demander l'approbation humaine.
    """
    state.status = AnalysisStatus.INSPECTION
    
    # Charger et inspecter les données avec DuckDB
    metadata = load_data(state.data_path)
    
    # Décider si une agrégation est nécessaire (si beaucoup de lignes)
    needs_agg = metadata["row_count"] > 10000
    
    return {
        "status": AnalysisStatus.AWAITING_APPROVAL,
        "data_metadata": metadata,
        "needs_aggregation": needs_agg,
        "audit_trail": state.audit_trail + [
            f"Inspection : {metadata['row_count']} lignes, "
            f"{len(metadata['schema'])} colonnes, "
            f"{metadata['duplicate_count']} doublons, "
            f"{len(metadata['null_counts'])} colonnes avec valeurs manquantes"
        ],
    }
