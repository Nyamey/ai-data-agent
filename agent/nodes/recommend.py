# agent/nodes/recommend.py — Nœud 6 : Recommandations
import json
from agent.state import AgentState, AnalysisStatus
from agent.llm.config import get_llm_response, extract_json


def recommend_node(state: AgentState) -> dict:
    """
    Nœud 6 : Recommandations.
    
    L'IA formule des recommandations actionnables basées sur les résultats,
    classées par impact, faisabilité et délai.
    """
    state.status = AnalysisStatus.RECOMMENDING
    
    significant_dims = [
        dim for dim, s in (state.statistical_tests or {}).items() if s.get("significant")
    ]

    # Rassembler tous les résultats pour le LLM
    context = f"""
    Question initiale : {state.business_question}
    Métrique : {state.metric_definition}

    Rétention hebdomadaire : {state.weekly_retention}

    Analyse des facteurs : {json.dumps(state.driver_analysis, default=str, indent=2)}

    Tests de significativité statistique (chi², p < 0.05 = significatif) :
    {json.dumps(state.statistical_tests, default=str, indent=2)}
    Dimensions statistiquement significatives : {significant_dims or "aucune"}

    Validation : {json.dumps(state.validation_checks, default=str, indent=2)}
    """

    prompt = f"""
    Tu es un analyste de données IA expert. Basé sur les résultats suivants,
    formule des recommandations actionnables. Priorise les dimensions
    statistiquement significatives (p < 0.05) : un écart significatif est un
    vrai signal, un écart non significatif peut n'être que du bruit
    d'échantillonnage -- dis-le explicitement si tu t'appuies sur une
    dimension non significative.

    {context}

    Produis UNIQUEMENT un JSON valide avec une liste de recommandations :
    {{
        "recommendations": [
            {{
                "title": "Titre court",
                "description": "Description détaillée",
                "impact": "élevé/moyen/faible",
                "feasibility": "élevée/moyenne/faible",
                "timeline": "court terme/moyen terme/long terme"
            }}
        ]
    }}
    
    Réponds en {state.output_language}.
    """
    
    response = get_llm_response(
        messages=[{"role": "user", "content": prompt}],
        provider=state.llm_provider,
        temperature=0.4,
    )
    
    try:
        result = extract_json(response)
        recommendations = result.get("recommendations", [])
    except json.JSONDecodeError:
        recommendations = [{"title": "Recommandations", "description": response}]
    
    return {
        "status": AnalysisStatus.EXPORTING,
        "recommendations": recommendations,
        "audit_trail": state.audit_trail + [
            f"Recommandations : {len(recommendations)} recommandations formulées"
        ],
    }
