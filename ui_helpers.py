# ui_helpers.py — Widgets d'affichage Streamlit partagés entre les deux
# modes de l'app (simple et agent), pour éviter que app.py et agent_ui.py
# ne s'importent l'un l'autre.
import pandas as pd
import streamlit as st


def render_missing_values(missing_by_column: dict):
    """Affiche les valeurs manquantes par colonne en tableau plutôt qu'en dict brut."""
    st.warning("Valeurs manquantes restantes :")
    st.dataframe(
        pd.DataFrame(
            {"Colonne": col, "Valeurs manquantes": count}
            for col, count in missing_by_column.items()
        ),
        use_container_width=True,
        hide_index=True,
    )


def render_date_range(date_range_by_column: dict):
    """Affiche la plage de dates par colonne en tableau plutôt qu'en dict brut imbriqué."""
    st.caption("Plage de dates :")
    st.dataframe(
        pd.DataFrame(
            {"Colonne": col, "Min": r.get("min"), "Max": r.get("max")}
            for col, r in date_range_by_column.items()
        ),
        use_container_width=True,
        hide_index=True,
    )


def render_llm_unavailable_warning(user_message: str, technical_detail: str = None):
    """Affiche un quota LLM épuisé comme un avertissement, pas une erreur bloquante.

    Une limite journalière atteinte (Groq/OpenRouter/Mistral) n'est pas un
    bug de l'application -- st.error() (rouge, ton alarmant) donnait
    pourtant cette impression. st.warning() communique mieux "c'est
    temporaire, réessayez plus tard".

    Le détail technique (traces litellm par provider) n'a rien à faire dans
    l'interface : un visiteur de l'app déployée n'a ni besoin ni moyen d'agir
    dessus (il ne peut pas configurer de clé API). Il part uniquement dans
    les logs serveur (console en local, "Manage app" → logs sur Streamlit
    Cloud), consultables par qui exploite l'app, pas par qui l'utilise.
    """
    st.warning(user_message)
    if technical_detail:
        print(f"[LLM indisponible] {technical_detail}")
