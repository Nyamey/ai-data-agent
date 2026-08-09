# simple_mode_ui.py — Mode « Analyse simple » (LLM en une passe)
#
# Séparé de app.py pour la même raison qu'agent_ui.py : un sous-système
# autonome (déclenchement de l'analyse, cascade de repli entre modèles
# gratuits, affichage du résultat et export) plutôt qu'un app.py fourre-tout.
import os
from datetime import datetime

import streamlit as st
from litellm import completion

from agent.llm.config import DEFAULT_MODELS, OPENROUTER_FALLBACK_MODELS
from app_utils import build_csv_export, build_excel_report, build_markdown_report, build_pptx_report
from ui_helpers import render_llm_unavailable_warning


def render_simple_mode(cleaned_files: list, describe_list: list, query: str, provider: str, current_source: tuple):
    """
    Lance (si demandé) l'analyse LLM en une passe puis affiche le dernier
    résultat correspondant aux fichiers/provider/question actuels.

    L'affichage est volontairement indépendant du déclenchement : les
    boutons de téléchargement provoquent un rerun Streamlit, qui ne doit
    pas faire disparaître le résultat déjà obtenu.
    """
    if st.session_state.get("analyze"):
        st.session_state["analyze"] = False
        if not cleaned_files:
            st.error("Aucun fichier n'a pu être lu correctement, l'analyse ne peut pas être lancée.")
        else:
            _run_simple_mode_analysis(cleaned_files, describe_list, query, provider, current_source)

    last_result = st.session_state.get("last_result")
    if last_result and last_result.get("source") == current_source:
        _render_simple_mode_result(last_result, cleaned_files)


def _run_simple_mode_analysis(
    cleaned_files: list, describe_list: list, query: str, provider: str, current_source: tuple,
):
    with st.spinner("Analyse en cours..."):
        # Préparer le contexte pour le LLM : un résumé par fichier
        summaries = []
        for (name, df), desc in zip(cleaned_files, describe_list):
            summaries.append(f"""
            ### Fichier : {name}
            - Nombre de lignes : {len(df)}
            - Colonnes : {', '.join(df.columns.tolist())}
            - Types de données : {df.dtypes.to_dict()}
            - Statistiques : {desc.to_dict()}
            - Premières lignes : {df.head(5).to_dict()}
            """)
        data_summary = "\n".join(summaries)

        # Choisir la liste de modèles à essayer selon le provider -- mêmes
        # constantes que le mode agent (agent/llm/config.py), pour ne pas
        # entretenir deux cascades de repli séparées qui pourraient diverger.
        if "Groq" in provider:
            candidates = [DEFAULT_MODELS["groq"]]
            api_key = os.getenv("GROQ_API_KEY")
        else:
            candidates = OPENROUTER_FALLBACK_MODELS
            api_key = os.getenv("OPENROUTER_API_KEY")

        prompt = f"""
        Tu es un analyste de données IA expert.

        Question : {query}

        Voici les données ({len(cleaned_files)} fichier(s)) :
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
            return

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
            except Exception as e:
                # Volontairement large : le but de cette boucle est de
                # basculer sur le modèle gratuit suivant quelle que soit
                # la cause de l'échec (auth, contexte trop long, réseau...).
                last_error = e
                continue

        if response is not None:
            analysis_text = response.choices[0].message.content
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

            st.session_state["last_result"] = {
                "timestamp": timestamp,
                "query": query,
                "model_used": model,
                "file_names": [name for name, _ in cleaned_files],
                "answer": analysis_text,
                "source": current_source,
            }
            st.session_state["history"].append(st.session_state["last_result"])
            st.session_state["history"] = st.session_state["history"][-20:]
        else:
            st.session_state["last_result"] = None
            render_llm_unavailable_warning(
                f"Tous les modèles gratuits sont temporairement indisponibles "
                f"({provider}). Réessaie dans quelques instants, ou choisis l'autre "
                "provider dans la barre latérale.",
                str(last_error),
            )


def _render_simple_mode_result(last_result: dict, cleaned_files: list):
    st.subheader("Analyse de l'IA")
    st.markdown(last_result["answer"])

    st.markdown("---")
    st.subheader("Exporter")
    csv_data, csv_name, csv_mime = build_csv_export(cleaned_files)
    dl1, dl2, dl3, dl4 = st.columns(4)
    dl1.download_button(
        "Rapport (Markdown)",
        data=build_markdown_report(
            last_result["query"], last_result["model_used"], cleaned_files,
            last_result["answer"], last_result["timestamp"],
        ),
        file_name="rapport_analyse.md",
        mime="text/markdown",
        use_container_width=True,
    )
    dl2.download_button(
        "Données nettoyées",
        data=csv_data,
        file_name=csv_name,
        mime=csv_mime,
        use_container_width=True,
    )
    dl3.download_button(
        "Rapport complet (Excel)",
        data=build_excel_report(cleaned_files, last_result["query"], last_result["model_used"], last_result["answer"]),
        file_name="rapport_analyse.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    dl4.download_button(
        "Présentation (PowerPoint)",
        data=build_pptx_report(
            last_result["query"], last_result["model_used"], cleaned_files,
            last_result["answer"], last_result["timestamp"],
        ),
        file_name="rapport_analyse.pptx",
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        use_container_width=True,
    )
