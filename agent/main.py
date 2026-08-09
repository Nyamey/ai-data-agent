# agent/main.py — Point d'entrée de l'agent
import uuid
from agent.graph import build_agent_graph
from agent.state import AgentState
from agent.nodes.approval import format_inspection_summary


def _print_progress(event: dict):
    print(f"\n[Statut : {event.get('status', 'En cours d\'exécution')}]")
    audit_trail = event.get("audit_trail")
    if audit_trail:
        print(f"  Dernière action : {audit_trail[-1]}")


def run_analysis(
    query: str,
    data_path: str,
    language: str = "fr",
    db_path: str = None,
    checkpoint_path: str = None,
    llm_provider: str = None,
):
    """
    Lance une analyse complète avec l'agent IA, avec un vrai point
    d'interruption avant l'approbation humaine (le graphe est compilé avec
    `interrupt_before=["approval"]" ; voir agent/graph.py).

    Args:
        query: La question d'analyse
        data_path: Chemin vers le fichier de données
        language: Langue des livrables (fr ou en)
        db_path: Chemin DuckDB à utiliser (par défaut DUCKDB_PATH) --
            utile pour isoler des analyses concurrentes
        checkpoint_path: Fichier de checkpoint SQLite de l'agent (par
            défaut ./data/agent_memory.db) -- utile pour isoler des
            analyses concurrentes
    """
    print("Démarrage de l'agent IA...")
    print(f"Question : {query}")
    print(f"Données : {data_path}")
    print(f"Langue : {language}")
    print("-" * 60)

    kwargs = {"checkpoint_path": checkpoint_path} if checkpoint_path else {}
    agent = build_agent_graph(**kwargs)

    initial_state = AgentState(
        query=query,
        data_path=data_path,
        output_language=language,
        db_path=db_path,
        llm_provider=llm_provider,
    )

    # Chaque appel a son propre fil de conversation LangGraph -- un
    # thread_id fixe ferait collisionner deux analyses successives (ou
    # concurrentes) sur le même historique de checkpoint.
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    # Phase 1 : cadrage + inspection, jusqu'au point d'interruption
    event = {}
    for event in agent.stream(initial_state, config=config, stream_mode="values"):
        _print_progress(event)

    # Le graphe s'est interrompu avant "approval" (sauf si l'inspection a
    # déjà terminé le flux en erreur, auquel cas il n'y a rien en attente)
    snapshot = agent.get_state(config)
    if snapshot.next == ("approval",):
        print("\n" + "=" * 60)
        print("RÉSUMÉ DE L'INSPECTION — APPROBATION REQUISE")
        print("=" * 60)
        print(format_inspection_summary(AgentState(**snapshot.values)))
        print("=" * 60)

        approval = input("\nApprouvez-vous la poursuite de l'analyse ? (oui/non) : ")
        approved = approval.strip().lower() in ["oui", "o", "yes", "y"]
        agent.update_state(config, {"approval_received": approved})

        for event in agent.stream(None, config=config, stream_mode="values"):
            _print_progress(event)

    print("\n" + "=" * 60)
    print("ANALYSE TERMINÉE")
    print("=" * 60)

    recommendations = event.get("recommendations") or []
    if recommendations:
        print("\nRecommandations :")
        for i, rec in enumerate(recommendations, 1):
            print(f"\n{i}. {rec.get('title', 'Sans titre')}")
            print(f"   {rec.get('description', '')}")
            print(f"   Impact : {rec.get('impact', 'N/A')} | "
                  f"Faisabilité : {rec.get('feasibility', 'N/A')} | "
                  f"Délai : {rec.get('timeline', 'N/A')}")
    elif event.get("errors"):
        print("\nErreurs :", event["errors"])

    return event


if __name__ == "__main__":
    result = run_analysis(
        query="Identifie ce qui explique la récente baisse de rétention client",
        data_path="data/sample_data.csv",
        language="fr",
    )
