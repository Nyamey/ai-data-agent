# agent/nodes/approval.py — Point de contrôle humain
from agent.state import AgentState, AnalysisStatus


def format_inspection_summary(state: AgentState) -> str:
    """
    Formate le résumé de cadrage + inspection présenté pour approbation.

    Réutilisable par n'importe quel appelant (CLI, interface web...) pour
    afficher la même information avant de recueillir la décision humaine.
    """
    lines = [
        f"Question : {state.business_question}",
        f"Métrique : {state.metric_definition}",
        f"Période : {state.comparison_period}",
        f"Données : {state.data_path}",
    ]
    if state.data_metadata:
        meta = state.data_metadata
        lines += [
            f"  - Lignes : {meta['row_count']}",
            f"  - Colonnes : {len(meta['schema'])}",
            f"  - Doublons : {meta['duplicate_count']}",
            f"  - Valeurs manquantes : {meta['null_counts']}",
            f"  - Plage de dates : {meta['date_range']}",
        ]
        # Présent uniquement en mode jointure (agent.tools.data_loader.load_joined_data) --
        # signale une jointure qui a probablement échoué (mauvaises colonnes
        # choisies) avant de gaspiller le reste de l'analyse dessus.
        if meta.get("join_warning"):
            lines.append(f"  - ATTENTION : {meta['join_warning']}")
    lines += [
        f"Agrégation nécessaire : {'Oui' if state.needs_aggregation else 'Non'}",
        f"Hypothèses : {state.assumptions}",
    ]
    return "\n".join(lines)


def approval_check_node(state: AgentState) -> dict:
    """
    Point de contrôle humain : traduit en statut la décision déjà recueillie
    par l'appelant.

    Le graphe est compilé avec `interrupt_before=["approval"]` (voir
    agent/graph.py) : l'exécution est réellement suspendue AVANT ce nœud,
    pas via un `input()` bloquant à l'intérieur. C'est à l'appelant de :
      1. Lire l'état interrompu (`graph.get_state(config)`) et afficher le
         résumé (`format_inspection_summary`) pour recueillir la décision
         humaine -- un `input()` dans un terminal, un bouton dans une UI
         web, peu importe.
      2. Appliquer la décision avec
         `graph.update_state(config, {"approval_received": bool})`.
      3. Reprendre l'exécution avec `graph.stream(None, config, ...)`.
    """
    if state.approval_received:
        return {
            "status": AnalysisStatus.BUILDING,
            "audit_trail": state.audit_trail + ["Approbation reçue de l'utilisateur"],
        }
    return {
        "status": AnalysisStatus.FAILED,
        "errors": state.errors + ["Analyse rejetée par l'utilisateur"],
    }
