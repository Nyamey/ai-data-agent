# agent/tools/chat_assistant.py — Assistant conversationnel sur les résultats d'une analyse
#
# Permet à l'utilisateur de poser des questions de suivi une fois l'analyse
# terminée (« pourquoi mobile est-il en tête ? », « et pour le mois dernier
# seulement ? »), avec un vrai accès à la table DuckDB de l'analyse plutôt
# qu'une simple relecture des résultats déjà calculés.
import json

from agent.llm.config import extract_json, get_llm_response
from agent.tools.data_loader import ensure_read_only_query, fetch_dataframe

# Cap sur le nombre de lignes réinjectées dans le prompt du second appel LLM
# -- une requête qui renvoie des milliers de lignes n'aiderait pas plus la
# réponse et gonflerait inutilement le prompt (coût, latence, risque de
# dépasser la fenêtre de contexte des modèles gratuits).
MAX_RESULT_ROWS = 200

# Nombre de tours d'historique conservés dans le prompt -- suffisant pour
# des questions de suivi ("et sur mobile ?" après "quelle plateforme domine
# ?"), sans faire grossir le prompt indéfiniment sur une longue conversation.
MAX_HISTORY_TURNS = 6


def _build_prompt(question, table_name, schema, analysis_context, history):
    schema_desc = "\n".join(f"- {s['column_name']} ({s['column_type']})" for s in schema)
    history_desc = "\n".join(
        f"{h['role']} : {h['content']}" for h in history[-MAX_HISTORY_TURNS:]
    ) or "(aucun)"

    return f"""
Tu es un analyste de données qui répond aux questions de suivi sur une
analyse déjà réalisée. Une table DuckDB est disponible : "{table_name}".

Colonnes disponibles :
{schema_desc}

Résumé de l'analyse déjà effectuée :
{analysis_context}

Historique récent de la conversation :
{history_desc}

Nouvelle question de l'utilisateur : {question}

Si répondre correctement nécessite de consulter les données (un chiffre
précis, un filtre, un tri, une comparaison non déjà calculée...), réponds
UNIQUEMENT avec un JSON de cette forme :
{{"needs_query": true, "sql": "UNE requête SELECT sur la table \\"{table_name}\\""}}

Sinon (la réponse découle directement du résumé ci-dessus, ou c'est une
question générale), réponds UNIQUEMENT avec :
{{"needs_query": false, "answer": "ta réponse en français"}}

La requête SQL, si tu en écris une, doit être une seule instruction de
lecture (SELECT/WITH), jamais une écriture ou une modification de schéma.
"""


def _build_followup_prompt(question, sql, result_text):
    return f"""
Question de l'utilisateur : {question}

Tu as exécuté cette requête pour y répondre :
{sql}

Résultat :
{result_text}

Formule maintenant une réponse claire et concise en français, basée
uniquement sur ce résultat. Si le résultat indique une erreur, explique-le
simplement à l'utilisateur et propose de reformuler la question -- ne
répète jamais le message d'erreur technique tel quel.
"""


def answer_question(
    question: str,
    table_name: str,
    schema: list[dict],
    analysis_context: str,
    history: list[dict],
    db_path: str = None,
    llm_provider: str = None,
) -> dict:
    """
    Répond à une question de suivi sur une analyse déjà terminée, en
    laissant le LLM décider s'il a besoin d'interroger la table DuckDB pour
    répondre.

    Suit le même patron « JSON + extract_json() » que framing_node/
    recommend_node plutôt que le tool-calling natif des API LLM (le
    paramètre "tools" n'est pas supporté de façon fiable par tous les
    modèles gratuits de la cascade OpenRouter) -- ce patron, lui, fonctionne
    identiquement quel que soit le provider/modèle utilisé.

    Le SQL généré par le LLM passe par ensure_read_only_query() avant toute
    exécution : une question utilisateur est une entrée non fiable au même
    titre qu'un appel MCP externe (voir mcp_server/server.py), et pourrait
    tenter d'orienter le LLM vers une requête d'écriture.

    Args:
        question: La question posée par l'utilisateur
        table_name: Nom de la table DuckDB de l'analyse (simple ou jointe)
        schema: Schéma de la table (liste de {"column_name", "column_type"})
        analysis_context: Résumé texte de l'analyse déjà réalisée
        history: Historique de la conversation, [{"role", "content"}, ...]
        db_path: Chemin DuckDB à interroger
        llm_provider: Provider LLM à utiliser (par défaut DEFAULT_LLM_PROVIDER)

    Returns:
        {"answer": str, "sql": str | None} -- `sql` est renseigné seulement
        si une requête a effectivement été exécutée (affichable à l'utilisateur
        pour la transparence).

    Raises:
        UserFacingError (LLMUnavailableError) : si aucun provider LLM
        configuré n'a pu répondre -- laissée remonter telle quelle pour que
        l'appelant l'affiche avec le même traitement que le reste de l'app.
    """
    prompt = _build_prompt(question, table_name, schema, analysis_context, history)
    response = get_llm_response(
        messages=[{"role": "user", "content": prompt}],
        provider=llm_provider,
        temperature=0.2,
    )

    try:
        decision = extract_json(response)
    except json.JSONDecodeError:
        # Comme framing_node : un LLM gratuit qui ne respecte pas la
        # consigne de format ne doit pas faire planter la conversation,
        # sa réponse en texte libre reste utilisable telle quelle.
        return {"answer": response, "sql": None}

    if not decision.get("needs_query"):
        return {"answer": decision.get("answer") or response, "sql": None}

    sql = decision.get("sql", "")
    try:
        ensure_read_only_query(sql)
        df = fetch_dataframe(sql, db_path=db_path)
        result_text = df.head(MAX_RESULT_ROWS).to_markdown(index=False)
    except Exception as e:
        # Le message technique part dans le prompt du second appel, pas
        # directement à l'écran : le LLM le reformule en explication simple
        # (voir _build_followup_prompt) -- même philosophie que
        # UserFacingError, appliquée ici via le LLM plutôt qu'un message figé.
        result_text = f"Erreur lors de l'exécution de la requête : {e}"

    followup = get_llm_response(
        messages=[{"role": "user", "content": _build_followup_prompt(question, sql, result_text)}],
        provider=llm_provider,
        temperature=0.2,
    )
    return {"answer": followup, "sql": sql}
