# agent/llm/config.py — Configuration LLM avec fallback automatique
import json
import os
import re
from litellm import completion
from dotenv import load_dotenv

load_dotenv()


def extract_json(text: str) -> dict:
    """
    Extrait un objet JSON de la réponse d'un LLM.

    Malgré la consigne "réponds UNIQUEMENT en JSON", beaucoup de modèles
    (surtout les plus petits/gratuits) ajoutent une phrase d'introduction ou
    enrobent la réponse dans un bloc ```json ... ``` -- un simple json.loads()
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

# Modèles gratuits OpenRouter essayés en cascade si l'un est rate-limité
# (pool partagé entre tous les utilisateurs OpenRouter, donc peu fiable seul)
OPENROUTER_FALLBACK_MODELS = [
    "openrouter/openai/gpt-oss-20b:free",
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter/google/gemma-4-31b-it:free",
]


def get_llm_response(
    messages: list[dict],
    provider: str = None,
    model: str = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """
    Obtient une réponse du LLM avec fallback automatique.

    Si le provider principal échoue, on bascule vers OpenRouter (modèle
    gratuit, sans compte de facturation requis -- contrairement à Gemini,
    dont l'accès via l'API Generative Language nécessite désormais une
    facturation activée sur de nombreux comptes).
    
    Args:
        messages: Liste de messages au format [{"role": "user", "content": "..."}]
        provider: Provider ("groq", "gemini", "openrouter", "mistral")
        model: Modèle spécifique (optionnel)
        temperature: 0 = précis, 1 = créatif
        max_tokens: Longueur maximale de la réponse
    
    Returns:
        La réponse texte du LLM
    """
    provider = provider or os.getenv("DEFAULT_LLM_PROVIDER", "groq")
    model = model or DEFAULT_MODELS.get(provider, DEFAULT_MODELS["groq"])
    
    # Récupérer la clé API correspondante
    api_keys = {
        "groq": os.getenv("GROQ_API_KEY"),
        "gemini": os.getenv("GOOGLE_API_KEY"),
        "openrouter": os.getenv("OPENROUTER_API_KEY"),
        "mistral": os.getenv("MISTRAL_API_KEY"),
    }
    
    try:
        response = completion(
            model=model,
            messages=messages,
            api_key=api_keys.get(provider),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content
    except Exception as e:
        if provider == "openrouter":
            # Déjà sur OpenRouter : le modèle gratuit demandé est rate-limité,
            # on essaie les autres avant d'abandonner (un seul modèle gratuit
            # tombe souvent en panne, sa charge étant partagée entre tous les
            # utilisateurs OpenRouter -- cf. app.py qui fait la même cascade).
            last_error = e
            for fallback_model in OPENROUTER_FALLBACK_MODELS:
                if fallback_model == model:
                    continue
                try:
                    response = completion(
                        model=fallback_model,
                        messages=messages,
                        api_key=api_keys.get("openrouter"),
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    return response.choices[0].message.content
                except Exception as e2:
                    last_error = e2
                    continue
            raise last_error
        else:
            print(f"Provider {provider} échoué ({e}). Bascule vers OpenRouter...")
            return get_llm_response(messages, provider="openrouter", temperature=temperature, max_tokens=max_tokens)
