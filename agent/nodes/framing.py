# agent/nodes/framing.py — Nœud 1 : Cadrage de l'analyse
import json
from agent.state import AgentState, AnalysisStatus
from agent.llm.config import get_llm_response


def framing_node(state: AgentState) -> dict:
    """
    Nœud 1 : Cadrage.
    
    L'IA définit :
    - La métrique de façon opérationnelle (ex. "rétention à 7 jours = ...")
    - La question commerciale reformulée et testable
    - La période de comparaison
    - Les hypothèses retenues
    
    C'est l'étape qui évite que l'analyse parte dans la mauvaise direction.
    """
    state.status = AnalysisStatus.FRAMING
    
    prompt = f"""
    Tu es un analyste de données IA expert. Analyse la demande suivante 
    et produit un cadrage structuré.
    
    Demande de l'utilisateur : {state.query}
    Fichier de données : {state.data_path}
    
    Produis UNIQUEMENT un JSON valide avec ces champs :
    {{
        "metric_definition": "définition opérationnelle de la métrique",
        "business_question": "la question commerciale reformulée de façon testable",
        "comparison_period": "période de comparaison (ex: mois dernier vs trimestre précédent)",
        "assumptions": ["hypothèse 1", "hypothèse 2"]
    }}
    
    Réponds en {state.output_language}.
    """
    
    response = get_llm_response(
        messages=[{"role": "user", "content": prompt}],
        provider=state.llm_provider,
        temperature=0.2,
    )
    
    try:
        framing = json.loads(response)
        return {
            "status": AnalysisStatus.INSPECTION,
            "metric_definition": framing.get("metric_definition", ""),
            "business_question": framing.get("business_question", ""),
            "comparison_period": framing.get("comparison_period", ""),
            "assumptions": framing.get("assumptions", []),
            "audit_trail": state.audit_trail + [
                f"Cadrage complété : {framing.get('business_question', '')}"
            ],
        }
    except json.JSONDecodeError:
        # Si le LLM ne renvoie pas du JSON valide, on récupère quand même le texte
        return {
            "status": AnalysisStatus.INSPECTION,
            "business_question": state.query,
            "metric_definition": "Non définie (erreur de parsing)",
            "comparison_period": "Non définie",
            "assumptions": [],
            "audit_trail": state.audit_trail + ["Cadrage : réponse non structurée"],
        }
