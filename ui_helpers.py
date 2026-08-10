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


def render_user_facing_error(user_message: str, technical_detail: str = None, severity: str = "error"):
    """Affiche une UserFacingError (agent/errors.py) sans jamais montrer son détail technique.

    `severity` distingue deux situations qui ne se présentent pas pareil :
    - "warning" : temporaire, pas la faute de l'utilisateur (ex. quota LLM
      épuisé) -- st.warning() (jaune) communique "réessayez plus tard", pas
      un blocage.
    - "error" : nécessite une action de l'utilisateur pour continuer (ex.
      jointure mal configurée) -- st.error() (rouge) attire l'attention sur
      ce qui doit être corrigé.

    Dans les deux cas, le détail technique (traces litellm/DuckDB, SQL
    généré, noms de table internes) n'a rien à faire dans l'interface : ni
    besoin ni moyen d'agir dessus pour qui visite l'app déployée (retour
    utilisateur explicite après qu'une trace DuckDB brute s'y soit
    retrouvée). Il part uniquement dans les logs serveur (console en local,
    "Manage app" → logs sur Streamlit Cloud), consultables par qui exploite
    l'app, pas par qui l'utilise.
    """
    (st.warning if severity == "warning" else st.error)(user_message)
    if technical_detail:
        print(f"[Erreur] {technical_detail}")
