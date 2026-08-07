# test_llm.py — Teste que l'API LLM fonctionne
import os
from dotenv import load_dotenv

# Charger les variables d'environnement depuis .env
load_dotenv()

# Vérifier que la clé API est présente
api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    print("ERREUR : Clé GROQ_API_KEY non trouvée dans .env")
    exit(1)

print("Clé API trouvée. Test de l'appel LLM...")

# Utiliser litellm pour appeler l'API (compatible avec tous les providers)
from litellm import completion

response = completion(
    model="groq/llama-3.3-70b-versatile",
    messages=[{"role": "user", "content": "Dis bonjour en français en une phrase."}],
    api_key=api_key,
    temperature=0.3,
    max_tokens=100,
)

print("\nRéponse du LLM :")
print(response.choices[0].message.content)
print("\nTest réussi ! L'API fonctionne.")
