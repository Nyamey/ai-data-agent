# app.py — Application Streamlit de base
import os
import re
import tempfile
import numpy as np
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from litellm import completion
from litellm.exceptions import RateLimitError, APIError, ServiceUnavailableError

# Modèles gratuits OpenRouter, essayés dans l'ordre si l'un est rate-limité
# (pool partagé entre tous les utilisateurs OpenRouter, donc peu fiable seul)
OPENROUTER_FREE_MODELS = [
    "openrouter/openai/gpt-oss-20b:free",
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter/google/gemma-4-31b-it:free",
]

DATE_KEYWORDS = ["date", "time", "jour", "mois", "annee", "année", "year"]
DECIMAL_PATTERN = re.compile(r"^-?\d+,\d+$")


def read_csv_robust(uploaded_file) -> tuple[pd.DataFrame, str]:
    """Lit un CSV en devinant l'encodage et le séparateur (utile pour les exports Excel FR)."""
    last_err = None
    for enc in ["utf-8-sig", "utf-8", "latin-1"]:
        try:
            uploaded_file.seek(0)
            df = pd.read_csv(uploaded_file, sep=None, engine="python", encoding=enc)
            return df, enc
        except Exception as e:
            last_err = e
            continue
    raise last_err


def clean_data(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Nettoie un DataFrame : types, doublons, texte, dates, décimales FR."""
    df = df.copy()
    original_rows, original_cols = df.shape

    # Noms de colonnes propres
    df.columns = [str(c).strip() for c in df.columns]

    # Lignes/colonnes entièrement vides
    df = df.dropna(axis=0, how="all")
    df = df.dropna(axis=1, how="all")
    rows_after_empty_drop = df.shape[0]

    # Texte : strip + chaînes vides -> NaN
    obj_cols = df.select_dtypes(include=["object", "str"]).columns
    for col in obj_cols:
        df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)
        df[col] = df[col].replace({"": np.nan})

    # Nombres au format européen ("120,50" -> 120.50)
    converted_decimal = []
    for col in df.select_dtypes(include=["object", "str"]).columns:
        sample = df[col].dropna().astype(str)
        if len(sample) > 0 and sample.str.match(DECIMAL_PATTERN).mean() > 0.7:
            df[col] = df[col].astype(str).str.replace(",", ".", regex=False)
            converted_decimal.append(col)

    # Colonnes numériques stockées en texte
    converted_numeric = []
    for col in df.select_dtypes(include=["object", "str"]).columns:
        converted = pd.to_numeric(df[col], errors="coerce")
        non_null = df[col].notna().sum()
        if non_null > 0 and converted.notna().sum() / non_null > 0.9:
            df[col] = converted
            converted_numeric.append(col)

    # Colonnes de dates (formats mixtes ISO / JJ-MM / MM-JJ)
    converted_dates = []
    for col in df.select_dtypes(include=["object", "str"]).columns:
        if any(k in col.lower() for k in DATE_KEYWORDS):
            parsed_eu = pd.to_datetime(df[col], errors="coerce", format="mixed", dayfirst=True)
            parsed_us = pd.to_datetime(df[col], errors="coerce", format="mixed", dayfirst=False)
            parsed = parsed_eu if parsed_eu.notna().sum() >= parsed_us.notna().sum() else parsed_us
            non_null = df[col].notna().sum()
            if non_null > 0 and parsed.notna().sum() / non_null > 0.7:
                df[col] = parsed
                converted_dates.append(col)

    # Doublons exacts
    duplicates_removed = int(df.duplicated().sum())
    df = df.drop_duplicates().reset_index(drop=True)

    missing_after = df.isna().sum()
    missing_after = {k: int(v) for k, v in missing_after[missing_after > 0].items()}

    report = {
        "original_rows": original_rows,
        "original_cols": original_cols,
        "final_rows": df.shape[0],
        "final_cols": df.shape[1],
        "empty_rows_removed": original_rows - rows_after_empty_drop,
        "duplicates_removed": duplicates_removed,
        "columns_converted_decimal": converted_decimal,
        "columns_converted_numeric": converted_numeric,
        "columns_converted_date": converted_dates,
        "missing_values": missing_after,
    }
    return df, report

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
        # Charger, nettoyer et prétraiter les données
        raw_df, encoding_used = read_csv_robust(uploaded_file)
        df, cleaning_report = clean_data(raw_df)

        with st.expander("🧹 Rapport de nettoyage des données", expanded=False):
            c1, c2, c3 = st.columns(3)
            c1.metric("Lignes conservées", f"{cleaning_report['final_rows']} / {cleaning_report['original_rows']}")
            c2.metric("Doublons supprimés", cleaning_report["duplicates_removed"])
            c3.metric("Lignes vides supprimées", cleaning_report["empty_rows_removed"])

            if encoding_used != "utf-8":
                st.caption(f"Encodage détecté et corrigé : {encoding_used}")
            if cleaning_report["columns_converted_decimal"]:
                st.caption(f"Format décimal FR converti (',' → '.') : {', '.join(cleaning_report['columns_converted_decimal'])}")
            if cleaning_report["columns_converted_numeric"]:
                st.caption(f"Colonnes converties en nombres : {', '.join(cleaning_report['columns_converted_numeric'])}")
            if cleaning_report["columns_converted_date"]:
                st.caption(f"Colonnes converties en dates : {', '.join(cleaning_report['columns_converted_date'])}")
            if cleaning_report["missing_values"]:
                st.warning(f"Valeurs manquantes restantes : {cleaning_report['missing_values']}")
            else:
                st.success("Aucune valeur manquante restante.")

        st.subheader(f"Aperçu des données nettoyées ({len(df)} lignes)")
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
                
                # Choisir la liste de modèles à essayer selon le provider
                if "Groq" in provider:
                    candidates = ["groq/llama-3.3-70b-versatile"]
                    api_key = os.getenv("GROQ_API_KEY")
                else:
                    candidates = OPENROUTER_FREE_MODELS
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
                    response = None
                    last_error = None
                    for model in candidates:
                        try:
                            response = completion(
                                model=model,
                                messages=[{"role": "user", "content": prompt}],
                                api_key=api_key,
                                temperature=0.3,
                                max_tokens=2000,
                            )
                            break
                        except (RateLimitError, APIError, ServiceUnavailableError) as e:
                            last_error = e
                            continue

                    if response is not None:
                        st.subheader("Analyse de l'IA")
                        st.markdown(response.choices[0].message.content)
                    else:
                        st.error(
                            f"Tous les modèles gratuits sont temporairement indisponibles "
                            f"({provider}). Réessaie dans quelques instants. Détail : {last_error}"
                        )
