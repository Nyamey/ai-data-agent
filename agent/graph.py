# agent/graph.py — Assemblage du graphe LangGraph
import sqlite3
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


def build_agent_graph():
    """
    Construit et compile le graphe de l'agent.
    
    Le graphe suit ce flux :
    Cadrage → Inspection → [Approbation] → Construction → Test → Validation → Recommandations
    
    Après l'inspection, l'agent s'arrête pour demander l'approbation.
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
    
    # Point d'entrée
    workflow.set_entry_point("framing")
    
    # Arêtes fixes (transitions directes)
    workflow.add_edge("framing", "inspection")
    workflow.add_edge("approval", "build")
    workflow.add_edge("build", "test")
    workflow.add_edge("test", "validate")
    workflow.add_edge("validate", "recommend")
    workflow.add_edge("recommend", END)
    
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
    conn = sqlite3.connect("./data/agent_memory.db", check_same_thread=False)
    memory = SqliteSaver(conn)
    
    return workflow.compile(checkpointer=memory)
