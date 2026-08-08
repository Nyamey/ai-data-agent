# agent/llm/config.py — Configuration LLM avec fallback automatique
import os
from litellm import completion
from dotenv import load_dotenv

load_dotenv()

# Mapping provider → modèle par défaut
DEFAULT_MODELS = {
    "groq": "groq/llama-3.3-70b-versatile",
    "gemini": "gemini/gemini-2.5-flash",
    "openrouter": "openrouter/openai/gpt-oss-20b:free",
    "mistral": "mistral/mistral-large-latest",
}


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
        # Si le provider échoue, essayer OpenRouter comme fallback
        if provider != "openrouter":
            print(f"Provider {provider} échoué ({e}). Bascule vers OpenRouter...")
            return get_llm_response(messages, provider="openrouter", temperature=temperature)
        raise
