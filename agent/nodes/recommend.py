# agent/nodes/recommend.py : nœud 6, recommandations
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
    
    uneven_dims = [
        dim for dim, s in (state.statistical_tests or {}).items() if s.get("significant")
    ]

    # Rassembler tous les résultats pour le LLM
    context = f"""
    Question initiale : {state.business_question}
    Métrique : {state.metric_definition}

    Rétention hebdomadaire : {state.weekly_retention}

    Répartition par dimension (effectif par catégorie) : {json.dumps(state.driver_analysis, default=str, indent=2)}

    Test du chi² d'ajustement par dimension (H0 : même effectif dans chaque
    catégorie ; "significant": true veut dire p < 0.05, répartition inégale) :
    {json.dumps(state.statistical_tests, default=str, indent=2)}
    Dimensions à répartition inégale : {uneven_dims or "aucune"}

    Validation : {json.dumps(state.validation_checks, default=str, indent=2)}
    """

    prompt = f"""
    Tu es un analyste de données IA expert. Basé sur les résultats suivants,
    formule des recommandations actionnables. Le test du chi² dit seulement
    si les effectifs sont répartis de façon inégale entre les catégories
    d'une dimension : il décrit l'échantillon, il ne compare pas la métrique
    entre catégories. Ne présente donc aucune dimension comme un facteur
    explicatif ou une cause sur cette base. Si une recommandation suppose un
    tel effet, dis que c'est une hypothèse à vérifier.

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
