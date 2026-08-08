# agent/main.py — Point d'entrée de l'agent
from agent.graph import build_agent_graph
from agent.state import AgentState


def run_analysis(query: str, data_path: str, language: str = "fr"):
    """
    Lance une analyse complète avec l'agent IA.
    
    Args:
        query: La question d'analyse
        data_path: Chemin vers le fichier de données
        language: Langue des livrables (fr ou en)
    """
    print("Démarrage de l'agent IA...")
    print(f"Question : {query}")
    print(f"Données : {data_path}")
    print(f"Langue : {language}")
    print("-" * 60)
    
    # Construire l'agent
    agent = build_agent_graph()
    
    # État initial
    initial_state = AgentState(
        query=query,
        data_path=data_path,
        output_language=language,
    )
    
    # Configuration avec thread_id pour la persistance
    config = {"configurable": {"thread_id": "analysis-001"}}
    
    # Exécuter en streaming (voir le progrès étape par étape)
    for event in agent.stream(initial_state, config=config, stream_mode="values"):
        # Utilisation de .get() avec une valeur par défaut au cas où 'status' n'est pas encore défini
        print(f"\n[Statut : {event.get('status', 'En cours d\'exécution')}]")
        
        # Récupération sécurisée de l'audit_trail
        audit_trail = event.get('audit_trail')
        if audit_trail:
            # On lit le dernier élément de la liste récupérée
            print(f"  Dernière action : {audit_trail[-1]}")
    
    print("\n" + "=" * 60)
    print("ANALYSE TERMINÉE")
    print("=" * 60)
    
    # Récupération sécurisée des recommandations à la fin de la boucle
    recommendations = event.get('recommendations', [])
    
    # Afficher les recommandations
    if recommendations:
        print("\nRecommandations :")
        for i, rec in enumerate(recommendations, 1):
            print(f"\n{i}. {rec.get('title', 'Sans titre')}")
            print(f"   {rec.get('description', '')}")
            print(f"   Impact : {rec.get('impact', 'N/A')} | "
                  f"Faisabilité : {rec.get('feasibility', 'N/A')} | "
                  f"Délai : {rec.get('timeline', 'N/A')}")
    
    return event


if __name__ == "__main__":
    result = run_analysis(
        query="Identifie ce qui explique la récente baisse de rétention client",
        data_path="data/sample_data.csv",
        language="fr",
    )