# agent/nodes/inspection.py — Nœud 2 : Inspection des données
from agent.state import AgentState, AnalysisStatus
from agent.tools.data_loader import load_data, load_joined_data


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

    # Mode jointure (plusieurs fichiers croisés) si join_spec est renseigné,
    # sinon comportement normal à un seul fichier -- voir agent/state.py.
    if state.join_spec:
        metadata = load_joined_data(state.data_paths, state.join_spec, db_path=state.db_path)
    else:
        metadata = load_data(state.data_path, db_path=state.db_path)
    
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
