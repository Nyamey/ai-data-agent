# app.py : point d'entrée Streamlit, coquille de page (config, barre
# latérale, téléversement/nettoyage) qui délègue chaque mode d'analyse à
# son propre module (simple_mode_ui.py, agent_ui.py).
import os

import streamlit as st
from dotenv import load_dotenv

from agent_ui import render_agent_mode
from app_utils import clean_data, read_csv_robust
from simple_mode_ui import render_simple_mode
from ui_helpers import render_missing_values

MAX_FILES = 5

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
    layout="wide",
)

# Titre
st.title("Agent IA d'Analyse de Données")
st.markdown("---")

st.session_state.setdefault("history", [])

# Barre latérale (sidebar)
with st.sidebar:
    st.header("Configuration")
    analysis_mode = st.radio(
        "Mode d'analyse",
        ["Analyse simple (LLM en une passe)", "Agent complet (8 étapes, avec validation humaine)"],
    )
    provider = st.selectbox(
        "Provider LLM",
        ["Groq (Llama 3.3 70B)", "OpenRouter (GPT-OSS 20B, gratuit)"],
        index=0,
    )
    st.markdown("---")
    st.markdown("### À propos")
    st.markdown("Agent IA pour l'analyse de données avec génération de livrables.")

    st.markdown("---")
    st.markdown("### Historique (session en cours)")
    if not st.session_state["history"]:
        st.caption("Aucune analyse pour l'instant.")
    else:
        for entry in reversed(st.session_state["history"]):
            with st.expander(f"{entry['timestamp']} · {entry['query'][:40]}"):
                st.caption(f"Modèle : {entry['model_used']} · fichiers : {', '.join(entry['file_names'])}")
                st.markdown(entry["answer"])

# Zone principale : deux colonnes
col1, col2 = st.columns([1, 2])

with col1:
    st.header("1. Données")

    # Téléversement de fichiers (jusqu'à MAX_FILES)
    uploaded_files = st.file_uploader(
        f"Téléverser jusqu'à {MAX_FILES} fichiers CSV",
        type=["csv"],
        accept_multiple_files=True,
    )
    if uploaded_files and len(uploaded_files) > MAX_FILES:
        st.warning(f"Maximum {MAX_FILES} fichiers : seuls les {MAX_FILES} premiers seront utilisés.")
        uploaded_files = uploaded_files[:MAX_FILES]

    # Question de l'utilisateur
    query = st.text_area(
        "2. Question d'analyse",
        value="Identifie ce qui explique la récente baisse de rétention client",
        height=100,
    )

    # Bouton de lancement
    is_agent_mode = analysis_mode.startswith("Agent complet")
    button_label = "Lancer le cadrage et l'inspection" if is_agent_mode else "Lancer l'analyse"
    trigger_key = "agent_trigger_inspect" if is_agent_mode else "analyze"
    if st.button(button_label, type="primary", use_container_width=True):
        if not uploaded_files:
            st.warning("Veuillez téléverser au moins un fichier CSV.")
        else:
            st.session_state[trigger_key] = True

with col2:
    st.header("Résultats")

    if uploaded_files:
        # Charger, nettoyer et prétraiter chaque fichier : une erreur sur un
        # fichier (encodage/format invalide) ne doit pas faire échouer les autres.
        cleaned_files = []  # list of (name, df)
        # Liste positionnelle (pas un dict par nom : deux fichiers peuvent
        # porter le même nom, ce qui écraserait silencieusement l'entrée).
        describe_list = []
        tabs = st.tabs([f.name for f in uploaded_files])
        for tab, file in zip(tabs, uploaded_files):
            with tab:
                try:
                    raw_df, encoding_used = read_csv_robust(file)
                    df, cleaning_report = clean_data(raw_df)
                except Exception as e:
                    st.error(f"Impossible de lire ce fichier : {e}")
                    continue

                # os.path.basename en défense en profondeur : le nom de fichier
                # atterrit ensuite dans des noms d'onglet Excel / d'entrée ZIP,
                # on évite qu'un séparateur de chemin s'y retrouve.
                safe_name = os.path.basename(file.name)
                cleaned_files.append((safe_name, df))
                file_describe = df.describe()
                describe_list.append(file_describe)

                with st.expander("Rapport de nettoyage des données", expanded=False):
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
                        render_missing_values(cleaning_report["missing_values"])
                    else:
                        st.success("Aucune valeur manquante restante.")

                st.subheader(f"Aperçu des données nettoyées ({len(df)} lignes)")
                st.dataframe(df.head(10), use_container_width=True)

                st.subheader("Statistiques descriptives")
                st.dataframe(file_describe, use_container_width=True)

        # Le résultat affiché ne doit rester valide que pour les mêmes fichiers,
        # le même provider ET la même question, sinon un simple changement de
        # question sans reclic sur "Lancer l'analyse" afficherait une réponse
        # qui ne correspond plus à ce qui est tapé à l'écran.
        current_source = (tuple(sorted((f.name, f.size) for f in uploaded_files)), provider, query)

        if is_agent_mode:
            if not cleaned_files:
                st.error("Aucun fichier n'a pu être lu correctement, l'analyse ne peut pas être lancée.")
            else:
                render_agent_mode(cleaned_files, query, provider, current_source)
        else:
            render_simple_mode(cleaned_files, describe_list, query, provider, current_source)
