# app.py — Application Streamlit de base
import os
import tempfile
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from litellm import completion

# Charger les variables d'environnement (local via .env, cloud via st.secrets)
load_dotenv()
try:
    for key, value in st.secrets.items():
        os.environ.setdefault(key, str(value))
except st.errors.StreamlitSecretNotFoundError:
    pass

# Configuration de la page
st.set_page_config(
    page_title="Agent IA d'Analyse de Données",
    page_icon="📊",
    layout="wide",
)

# Titre
st.title("Agent IA d'Analyse de Données")
st.markdown("---")

# Barre latérale (sidebar)
with st.sidebar:
    st.header("Configuration")
    provider = st.selectbox(
        "Provider LLM",
        ["Groq (Llama 3.3 70B)", "OpenRouter (GPT-OSS 20B, gratuit)"],
        index=0,
    )
    st.markdown("---")
    st.markdown("### À propos")
    st.markdown("Agent IA pour l'analyse de données avec génération de livrables.")

# Zone principale — deux colonnes
col1, col2 = st.columns([1, 2])

with col1:
    st.header("1. Données")
    
    # Téléversement de fichier
    uploaded_file = st.file_uploader(
        "Téléverser un fichier CSV",
        type=["csv"],
    )
    
    # Question de l'utilisateur
    query = st.text_area(
        "2. Question d'analyse",
        value="Identifie ce qui explique la récente baisse de rétention client",
        height=100,
    )
    
    # Bouton de lancement
    if st.button("Lancer l'analyse", type="primary", use_container_width=True):
        if not uploaded_file:
            st.warning("Veuillez téléverser un fichier CSV.")
        else:
            st.session_state["analyze"] = True

with col2:
    st.header("Résultats")
    
    if uploaded_file is not None:
        # Charger et afficher les données
        df = pd.read_csv(uploaded_file)
        st.subheader(f"Aperçu des données ({len(df)} lignes)")
        st.dataframe(df.head(10), use_container_width=True)
        
        # Statistiques de base
        st.subheader("Statistiques descriptives")
        st.dataframe(df.describe(), use_container_width=True)
        
        # Si on a cliqué sur "Lancer l'analyse"
        if st.session_state.get("analyze"):
            with st.spinner("Analyse en cours..."):
                # Préparer le contexte pour le LLM
                data_summary = f"""
                - Nombre de lignes : {len(df)}
                - Colonnes : {', '.join(df.columns.tolist())}
                - Types de données : {df.dtypes.to_dict()}
                - Statistiques : {df.describe().to_dict()}
                - Premières lignes : {df.head(5).to_dict()}
                """
                
                # Choisir le modèle selon le provider
                if "Groq" in provider:
                    model = "groq/llama-3.3-70b-versatile"
                    api_key = os.getenv("GROQ_API_KEY")
                else:
                    model = "openrouter/openai/gpt-oss-20b:free"
                    api_key = os.getenv("OPENROUTER_API_KEY")
                
                prompt = f"""
                Tu es un analyste de données IA expert.
                
                Question : {query}
                
                Voici les données :
                {data_summary}
                
                Fournis une analyse structurée en français avec :
                1. Cadrage (définition de la métrique, période)
                2. Observations clés
                3. Facteurs explicatifs possibles
                4. Recommandations
                """
                
                if not api_key:
                    st.error(
                        "Clé API manquante pour ce provider. "
                        "Vérifie GROQ_API_KEY / OPENROUTER_API_KEY dans tes secrets."
                    )
                else:
                    try:
                        response = completion(
                            model=model,
                            messages=[{"role": "user", "content": prompt}],
                            api_key=api_key,
                            temperature=0.3,
                            max_tokens=2000,
                        )
                        st.subheader("Analyse de l'IA")
                        st.markdown(response.choices[0].message.content)
                    except Exception as e:
                        st.error(f"Erreur lors de l'appel au LLM ({provider}) : {e}")
