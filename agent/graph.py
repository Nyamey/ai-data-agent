# agent/graph.py : assemblage du graphe LangGraph
import sqlite3
from pathlib import Path
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from agent.state import AgentState, AnalysisStatus
from agent.nodes.framing import framing_node
from agent.nodes.inspection import inspection_node
from agent.nodes.approval import approval_check_node
from agent.nodes.build import build_node
from agent.nodes.test import test_node
from agent.nodes.validate import validate_node
from agent.nodes.recommend import recommend_node
from agent.nodes.export import export_node


def build_agent_graph(checkpoint_path: str = "./data/agent_memory.db"):
    """
    Construit et compile le graphe de l'agent.

    Le graphe suit ce flux :
    Cadrage → Inspection → [Approbation] → Construction → Test → Validation → Recommandations → Export

    Le graphe s'interrompt réellement avant le nœud "approval" (via
    `interrupt_before`, mécanisme natif LangGraph) plutôt que de bloquer sur
    un `input()` dans le nœud lui-même, ce qui permet de reprendre
    l'exécution depuis n'importe quel appelant (CLI interactif, UI web...),
    chacun décidant comment recueillir l'approbation avant d'appeler
    `update_state` puis de reprendre le stream.

    Args:
        checkpoint_path: Fichier SQLite de checkpoint. Utiliser un chemin
            distinct par session/utilisateur pour isoler les exécutions
            concurrentes (ex. plusieurs sessions Streamlit).
    """
    workflow = StateGraph(AgentState)
    
    # Ajouter tous les nœuds
    workflow.add_node("framing", framing_node)
    workflow.add_node("inspection", inspection_node)
    workflow.add_node("approval", approval_check_node)
    workflow.add_node("build", build_node)
    workflow.add_node("test", test_node)
    workflow.add_node("validate", validate_node)
    workflow.add_node("recommend", recommend_node)
    workflow.add_node("export", export_node)

    # Point d'entrée
    workflow.set_entry_point("framing")

    # Arêtes fixes (transitions directes)
    workflow.add_edge("framing", "inspection")
    workflow.add_edge("build", "test")
    workflow.add_edge("test", "validate")
    workflow.add_edge("validate", "recommend")
    workflow.add_edge("recommend", "export")
    workflow.add_edge("export", END)
    
    # Arête conditionnelle après l'inspection :
    # si on attend l'approbation → aller au point de contrôle
    # si erreur → finir
    workflow.add_conditional_edges(
        "inspection",
        lambda state: "approval" 
            if state.status == AnalysisStatus.AWAITING_APPROVAL 
            else END,
        {"approval": "approval", END: END},
    )
    
    # Arête conditionnelle après l'approbation :
    # si approuvé → construction
    # si rejeté → finir
    workflow.add_conditional_edges(
        "approval",
        lambda state: "build" 
            if state.status == AnalysisStatus.BUILDING 
            else END,
        {"build": "build", END: END},
    )
    
    # Compiler avec persistance SQLite (sauvegarde de l'état)
    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
    memory = SqliteSaver(conn)

    return workflow.compile(checkpointer=memory, interrupt_before=["approval"])
