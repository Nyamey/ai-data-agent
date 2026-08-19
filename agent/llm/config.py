# agent/llm/config.py : configuration LLM avec repli automatique
import json
import os
import re
from litellm import completion
from dotenv import load_dotenv

from agent.errors import UserFacingError

load_dotenv()


def extract_json(text: str) -> dict:
    """
    Extrait un objet JSON de la réponse d'un LLM.

    Malgré la consigne "réponds UNIQUEMENT en JSON", beaucoup de modèles
    (surtout les plus petits/gratuits) ajoutent une phrase d'introduction ou
    enrobent la réponse dans un bloc ```json ... ```, un simple json.loads()
    échoue alors sur du JSON pourtant valide une fois isolé. Essaie plusieurs
    stratégies avant d'abandonner.
    """
    text = text.strip()

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start:end + 1])

    raise json.JSONDecodeError("Impossible d'extraire un JSON valide", text, 0)

# Mapping provider → modèle par défaut
DEFAULT_MODELS = {
    "groq": "groq/llama-3.3-70b-versatile",
    "gemini": "gemini/gemini-2.5-flash",
    "openrouter": "openrouter/openai/gpt-oss-20b:free",
    "mistral": "mistral/mistral-large-latest",
}

# Modèles gratuits OpenRouter essayés en cascade si l'un atteint sa limite
# de requêtes. Ça aide contre une panne ou une limite propre à UN modèle,
# mais OpenRouter applique aussi un plafond quotidien de requêtes gratuites
# au niveau du COMPTE ("free-models-per-day"), partagé par tous les modèles
# :free : une fois ce plafond atteint, les trois échouent identiquement et
# aucune cascade de modèles n'y changera rien tant qu'il n'est pas
# réinitialisé (ou des crédits ajoutés), d'où le repli vers un autre
# provider ci-dessous, seul recours dans ce cas précis.
OPENROUTER_FALLBACK_MODELS = [
    "openrouter/openai/gpt-oss-20b:free",
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter/google/gemma-4-31b-it:free",
]

# Ordre d'essai des providers quand celui demandé échoue. Gemini est exclu
# du repli automatique (accès payant sur de nombreux comptes désormais,
# voir README) mais reste utilisable si explicitement demandé.
PROVIDER_FALLBACK_ORDER = ["groq", "openrouter", "mistral"]


class LLMUnavailableError(UserFacingError):
    """Levée quand aucun provider LLM configuré n'a pu répondre.

    Un quota épuisé ou une panne de provider est temporaire et n'est pas la
    faute de l'utilisateur : severity="warning" (voir UserFacingError)
    pour que l'UI l'affiche comme "réessayez plus tard", pas comme un
    blocage nécessitant une action.
    """

    severity = "warning"


def _api_key_for(provider: str) -> str | None:
    return {
        "groq": os.getenv("GROQ_API_KEY"),
        "gemini": os.getenv("GOOGLE_API_KEY"),
        "openrouter": os.getenv("OPENROUTER_API_KEY"),
        "mistral": os.getenv("MISTRAL_API_KEY"),
    }.get(provider)


def _try_provider(provider: str, messages: list[dict], temperature: float, max_tokens: int):
    """
    Essaie un provider (avec sa propre cascade de modèles pour OpenRouter).

    Returns:
        (texte, None) en cas de succès.
        (None, None) si le provider n'a pas de clé API configurée : pas un
        échec à proprement parler, juste une option indisponible.
        (None, dernière_exception) si tous les modèles de ce provider ont échoué.
    """
    api_key = _api_key_for(provider)
    if not api_key:
        return None, None

    models = OPENROUTER_FALLBACK_MODELS if provider == "openrouter" else [DEFAULT_MODELS[provider]]
    last_error = None
    for model in models:
        try:
            response = completion(
                model=model, messages=messages, api_key=api_key,
                temperature=temperature, max_tokens=max_tokens,
            )
            return response.choices[0].message.content, None
        except Exception as e:
            last_error = e
            continue
    return None, last_error


def get_llm_response(
    messages: list[dict],
    provider: str = None,
    model: str = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """
    Obtient une réponse du LLM avec repli automatique vers un autre provider.

    Si le provider demandé échoue (quota, panne...), on essaie les autres
    providers configurés (ceux avec une clé API renseignée) dans l'ordre de
    PROVIDER_FALLBACK_ORDER, avant d'abandonner.

    Args:
        messages: Liste de messages au format [{"role": "user", "content": "..."}]
        provider: Provider ("groq", "gemini", "openrouter", "mistral")
        model: Modèle spécifique à utiliser pour le provider demandé (optionnel),
            n'affecte pas les modèles utilisés par les providers de repli
        temperature: 0 = précis, 1 = créatif
        max_tokens: Longueur maximale de la réponse

    Returns:
        La réponse texte du LLM

    Raises:
        LLMUnavailableError: si aucun provider configuré n'a pu répondre.
    """
    requested = provider or os.getenv("DEFAULT_LLM_PROVIDER", "groq")

    if model:
        # Modèle explicitement demandé : un seul essai sur ce provider précis,
        # sans passer par _try_provider() (qui impose les modèles par défaut).
        api_key = _api_key_for(requested)
        response = completion(
            model=model, messages=messages, api_key=api_key,
            temperature=temperature, max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    # Le provider demandé passe en premier, puis les autres providers
    # configurés comme filet de secours, chacun une seule fois.
    order = [requested] + [p for p in PROVIDER_FALLBACK_ORDER if p != requested]

    errors = {}
    for p in order:
        text, error = _try_provider(p, messages, temperature, max_tokens)
        if text is not None:
            if p != requested:
                print(f"Provider {requested} indisponible, bascule réussie vers {p}.")
            return text
        if error is not None:
            errors[p] = error

    if not errors:
        # Message pour l'utilisateur final de l'app déployée : il ne peut de
        # toute façon pas configurer de clé API lui-même. Cette instruction
        # ne concerne que l'administrateur, reléguée dans technical_detail.
        raise LLMUnavailableError(
            "Le service d'analyse IA n'est pas configuré pour le moment. "
            "Merci de réessayer plus tard.",
            technical_detail=(
                "Aucun provider LLM configuré : renseignez au moins une clé API "
                "(GROQ_API_KEY, OPENROUTER_API_KEY ou MISTRAL_API_KEY)."
            ),
        )
    detail = " ; ".join(f"{p} : {e}" for p, e in errors.items())
    raise LLMUnavailableError(
        "Tous les providers LLM configurés sont actuellement indisponibles "
        "(quota journalier atteint ou panne temporaire). Réessayez plus tard.",
        technical_detail=detail,
    )
