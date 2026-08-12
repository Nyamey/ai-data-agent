# agent_ui.py — Mode « Agent complet » (8 étapes) de l'interface Streamlit
#
# Séparé de app.py (qui garde la coquille de page + le mode « Analyse
# simple ») parce que ce sous-système a sa propre logique conséquente :
# configuration de jointure multi-fichiers, lancement du graphe LangGraph
# jusqu'au point d'interruption, cycle d'approbation humaine, affichage des
# résultats. Regrouper tout ça ici évite un app.py fourre-tout.
import os
import re
import tempfile
import uuid

import pandas as pd
import streamlit as st

from agent.errors import UserFacingError
from agent.graph import build_agent_graph
from agent.output.excel_generator import ExcelGenerator
from agent.state import AgentState
from agent.tools.chat_assistant import answer_question
from agent.tools.data_loader import fetch_dataframe, quote_ident
from ui_helpers import render_date_range, render_missing_values, render_user_facing_error

# Libellés affichés pendant graph.stream(...) pour que l'utilisateur voie
# quelle étape tourne, plutôt qu'un seul spinner statique pendant toute la
# séquence (le nœud "recommend" à lui seul appelle un LLM, donc l'ensemble
# construction/test/validation/recommandations/export peut prendre plusieurs
# secondes sans aucun retour visuel jusqu'ici).
_STEP_LABELS = {
    "cadrage": "Cadrage de la question",
    "inspection": "Inspection des données",
    "construction": "Construction de la métrique",
    "test": "Test des facteurs explicatifs",
    "validation": "Validation des résultats",
    "recommandations": "Formulation des recommandations",
    "export": "Génération des livrables (Excel / PowerPoint)",
    "termine": "Terminé",
    "echec": "Erreur",
}


def _show_step_progress(placeholder, event: dict):
    """Affiche l'étape en cours à partir d'un événement de graph.stream(...).

    `status` est un AnalysisStatus (str, Enum) : getattr(..., "value", ...)
    récupère sa valeur brute qu'il s'agisse d'un enum ou déjà d'une chaîne
    (selon le point exact du cycle LangGraph où l'état est observé).
    """
    status = event.get("status")
    if status is None:
        return
    status_value = getattr(status, "value", status)
    placeholder.caption(f"Étape en cours : {_STEP_LABELS.get(status_value, status_value)}")


def render_agent_mode(cleaned_files: list, query: str, provider: str, current_source: tuple):
    """
    Pilote le workflow agent en 8 étapes (agent/graph.py) depuis l'UI.

    Deux modes quand plusieurs fichiers sont téléversés :
    - Indépendant (par défaut) : un onglet par fichier, chacun son propre
      cycle cadrage / inspection / approbation / résultats, complètement
      indépendant des autres (fil de checkpoint, base DuckDB et décision
      d'approbation propres à chaque fichier). Le graphe LangGraph n'a pas
      de notion native de "plusieurs fichiers", donc il n'y a pas d'analyse
      croisée dans ce mode.
    - Jointure : les fichiers sont chargés dans une seule table DuckDB
      croisée (voir agent.tools.data_loader.load_joined_data) selon un
      arbre de jointure configuré par l'utilisateur, puis analysés comme un
      cycle unique -- build/test/validate ne voient qu'une table, peu
      importe son origine.

    Le graphe est compilé avec `interrupt_before=["approval"]` : il s'arrête
    réellement avant l'étape d'approbation (pas de input() bloquant). Cette
    fonction affiche le cadrage/l'inspection, recueille la décision humaine
    via deux boutons, puis reprend l'exécution avec `update_state` +
    `stream(None, ...)`.

    Chaque session Streamlit utilise ses propres fichiers DuckDB et de
    checkpoint pour ne pas interférer avec les autres utilisateurs.
    """
    session_dir = st.session_state.setdefault(
        "agent_session_dir", tempfile.mkdtemp(prefix="ai_data_agent_")
    )
    llm_provider = "groq" if "Groq" in provider else "openrouter"
    runs = st.session_state.setdefault("agent_runs", {})

    join_spec_by_name = None
    if len(cleaned_files) >= 2:
        mode_choice = st.radio(
            "Comment analyser ces fichiers ?",
            ["Indépendamment (un cycle par fichier)", "Croisés par jointure (un seul cycle)"],
            key="agent_join_mode_choice",
        )
        if mode_choice.startswith("Croisés"):
            join_spec_by_name = _render_join_config_ui(cleaned_files)

    if st.session_state.get("agent_trigger_inspect"):
        st.session_state["agent_trigger_inspect"] = False
        if join_spec_by_name is not None:
            _start_joint_agent_inspection(
                join_spec_by_name, cleaned_files, query, llm_provider, session_dir, current_source, runs
            )
        else:
            for i, (name, df) in enumerate(cleaned_files):
                run_key = f"{i}_{name}"
                _start_agent_inspection(
                    run_key, name, df, query, llm_provider, session_dir, current_source, runs
                )

    if join_spec_by_name is not None:
        _render_single_agent_run("join_0", current_source, runs, llm_provider)
        return

    if len(cleaned_files) == 1:
        name, _ = cleaned_files[0]
        _render_single_agent_run(f"0_{name}", current_source, runs, llm_provider)
        return

    tabs = st.tabs([name for name, _ in cleaned_files])
    for i, (tab, (name, _)) in enumerate(zip(tabs, cleaned_files)):
        with tab:
            _render_single_agent_run(f"{i}_{name}", current_source, runs, llm_provider)


def _render_join_config_ui(cleaned_files: list) -> dict:
    """
    Affiche les sélecteurs de configuration de la jointure et renvoie le
    join_spec construit (indexé par nom de fichier -- traduit en chemins
    réels par _start_joint_agent_inspection juste avant de lancer l'agent).

    Pas de détection automatique de clé de jointure (trop fragile) :
    l'utilisateur choisit un fichier racine, puis pour chaque autre fichier
    (dans l'ordre de téléversement), à quel fichier déjà inclus il se
    rattache et sur quelles colonnes -- ça construit un arbre de jointure
    connexe, sans limite sur le nombre de fichiers.
    """
    file_names = [name for name, _ in cleaned_files]
    columns_by_name = {name: list(df.columns) for name, df in cleaned_files}

    st.markdown("##### Configuration de la jointure")
    root = st.selectbox("Fichier racine", file_names, key="join_root")

    included = [root]
    joins = []
    for name in [n for n in file_names if n != root]:
        st.caption(f"Rattacher **{name}** :")
        c1, c2, c3, c4 = st.columns(4)

        # Les options de ces sélecteurs dépendent du fichier racine choisi
        # et changent d'un rerun à l'autre : si la valeur mémorisée n'est
        # plus valide, la remettre à une valeur par défaut avant de rendre
        # le widget évite une StreamlitAPIException (valeur hors options).
        on_file_key = f"join_on_file_{name}"
        if st.session_state.get(on_file_key) not in included:
            st.session_state[on_file_key] = included[0]
        on_file = c1.selectbox("à", included, key=on_file_key)

        on_col_key = f"join_on_col_{name}_{on_file}"
        on_columns = columns_by_name[on_file]
        if st.session_state.get(on_col_key) not in on_columns:
            st.session_state[on_col_key] = on_columns[0]
        on_col = c3.selectbox(f"colonne de {on_file}", on_columns, key=on_col_key)

        file_col = c2.selectbox(f"colonne de {name}", columns_by_name[name], key=f"join_file_col_{name}")
        how = c4.selectbox("type", ["inner", "left"], key=f"join_how_{name}")

        joins.append({
            "file": name, "on_file": on_file,
            "file_column": file_col, "on_column": on_col, "how": how,
        })
        included.append(name)

    return {"root": root, "joins": joins}


def _write_session_csv(df: pd.DataFrame, name: str, session_dir: str) -> str:
    """Écrit un DataFrame nettoyé dans le dossier de session, nom de fichier assaini.

    `name` porte déjà l'extension d'origine (ex. "commandes.csv") : on la
    retire avant de rajouter la nôtre, sinon le fichier écrit se retrouve en
    ".csv.csv" -- ce qui, en mode jointure, pollue aussi le préfixe de
    colonne dérivé du nom de table (ex. "data_commandes_csv__id" au lieu de
    "data_commandes__id").
    """
    stem = re.sub(r"[^\w.-]", "_", os.path.splitext(name)[0])
    csv_path = os.path.join(session_dir, f"data_{stem}.csv")
    df.to_csv(csv_path, index=False)
    return csv_path


def _start_joint_agent_inspection(
    join_spec_by_name: dict, cleaned_files: list, query: str, llm_provider: str,
    session_dir: str, current_source: tuple, runs: dict,
):
    """Lance le cadrage + l'inspection pour une analyse croisée (jointure de plusieurs fichiers)."""
    run_key = "join_0"
    name_to_path = {name: _write_session_csv(df, name, session_dir) for name, df in cleaned_files}

    involved_names = [join_spec_by_name["root"]] + [s["file"] for s in join_spec_by_name["joins"]]
    csv_paths = [name_to_path[n] for n in involved_names]
    join_spec = {
        "root": name_to_path[join_spec_by_name["root"]],
        "joins": [
            {
                "file": name_to_path[s["file"]],
                "on_file": name_to_path[s["on_file"]],
                "file_column": s["file_column"],
                "on_column": s["on_column"],
                "how": s["how"],
            }
            for s in join_spec_by_name["joins"]
        ],
    }

    thread_id = str(uuid.uuid4())
    checkpoint_path = os.path.join(session_dir, f"checkpoint_{thread_id}.db")
    db_path = os.path.join(session_dir, f"analytics_{thread_id}.duckdb")
    initial_state = AgentState(
        query=query, data_path=csv_paths[0], data_paths=csv_paths, join_spec=join_spec,
        db_path=db_path, llm_provider=llm_provider,
    )
    _run_inspection_graph(
        run_key, initial_state, thread_id, checkpoint_path, current_source, runs,
        "Cadrage et inspection en cours (fichiers croisés)...",
    )


def _start_agent_inspection(
    run_key: str, name: str, df: pd.DataFrame, query: str, llm_provider: str,
    session_dir: str, current_source: tuple, runs: dict,
):
    """Lance le cadrage + l'inspection pour un fichier, jusqu'au point d'interruption."""
    csv_path = _write_session_csv(df, run_key, session_dir)

    thread_id = str(uuid.uuid4())
    checkpoint_path = os.path.join(session_dir, f"checkpoint_{thread_id}.db")
    db_path = os.path.join(session_dir, f"analytics_{thread_id}.duckdb")
    initial_state = AgentState(
        query=query, data_path=csv_path, db_path=db_path, llm_provider=llm_provider,
    )
    _run_inspection_graph(
        run_key, initial_state, thread_id, checkpoint_path, current_source, runs,
        f"Cadrage et inspection en cours pour {name}...",
    )


def _run_inspection_graph(
    run_key: str, initial_state: AgentState, thread_id: str, checkpoint_path: str,
    current_source: tuple, runs: dict, spinner_text: str,
):
    """
    Exécute le graphe jusqu'au point d'interruption et range le résultat dans `runs`.

    Factorisé hors de _start_agent_inspection()/_start_joint_agent_inspection()
    (mono-fichier vs jointure) : au-delà de la construction de l'état initial,
    les deux lancent le graphe et gèrent ses échecs de façon identique.

    Distingue UserFacingError (agent/errors.py -- un message déjà pensé pour
    l'utilisateur : quota LLM épuisé, jointure mal configurée...) des autres
    exceptions, pour que _render_single_agent_run() l'affiche proprement
    (message clair, détail technique relégué aux logs) plutôt que de
    laisser passer une trace brute -- voir render_user_facing_error().
    """
    try:
        with st.spinner(spinner_text):
            progress = st.empty()
            graph = build_agent_graph(checkpoint_path=checkpoint_path)
            config = {"configurable": {"thread_id": thread_id}}
            for event in graph.stream(initial_state, config=config, stream_mode="values"):
                _show_step_progress(progress, event)
            progress.empty()
            snapshot = graph.get_state(config)
    except UserFacingError as e:
        # getattr() en défense en profondeur : un redéploiement Streamlit
        # Cloud a déjà surpris une instance encore sur l'ancienne classe
        # d'exception (sans ces attributs) pendant la bascule -- jamais une
        # AttributeError ici, même dans ce cas transitoire.
        runs[run_key] = {
            "source": current_source,
            "user_error": getattr(e, "user_message", str(e)),
            "error_detail": getattr(e, "technical_detail", None),
            "error_severity": getattr(e, "severity", "error"),
        }
        return
    except Exception as e:
        runs[run_key] = {"source": current_source, "error": str(e)}
        return

    runs[run_key] = {
        "source": current_source,
        "thread_id": thread_id,
        "checkpoint_path": checkpoint_path,
        "awaiting_approval": snapshot.next == ("approval",),
        "snapshot_values": snapshot.values,
        "final_event": None,
    }


def _render_single_agent_run(run_key: str, current_source: tuple, runs: dict, llm_provider: str):
    """Affiche le cycle complet (cadrage/inspection/approbation/résultats) d'un fichier."""
    run = runs.get(run_key)
    if not run or run.get("source") != current_source:
        st.info('Clique sur "Lancer le cadrage et l\'inspection" pour démarrer.')
        return

    if run.get("user_error"):
        render_user_facing_error(run["user_error"], run.get("error_detail"), run.get("error_severity", "error"))
        return

    if run.get("error"):
        st.error(f"Le cadrage/l'inspection a échoué : {run['error']}")
        return

    values = run["snapshot_values"]

    st.subheader("Cadrage")
    st.write("**Question reformulée :**", values.get("business_question"))
    st.write("**Métrique :**", values.get("metric_definition") or "Non définie")
    st.write("**Période de comparaison :**", values.get("comparison_period") or "Non définie")
    if values.get("assumptions"):
        st.write("**Hypothèses :**", ", ".join(values["assumptions"]))

    meta = values.get("data_metadata") or {}
    st.subheader("Inspection des données")
    i1, i2, i3 = st.columns(3)
    i1.metric("Lignes", meta.get("row_count", "-"))
    i2.metric("Colonnes", len(meta.get("schema", [])))
    i3.metric("Doublons", meta.get("duplicate_count", "-"))
    st.write("**Colonne identifiant détectée :**", meta.get("id_column") or "Aucune")
    if meta.get("source_row_counts"):
        st.caption("Lignes par fichier avant jointure :")
        st.dataframe(
            pd.DataFrame(
                {"Fichier": os.path.basename(p), "Lignes": c}
                for p, c in meta["source_row_counts"].items()
            ),
            use_container_width=True, hide_index=True,
        )
    if meta.get("join_warning"):
        st.warning(meta["join_warning"])
    if meta.get("null_counts"):
        render_missing_values(meta["null_counts"])
    if meta.get("date_range"):
        render_date_range(meta["date_range"])

    if not run["awaiting_approval"]:
        st.error("L'inspection s'est terminée en erreur avant le point d'approbation.")
        return

    if run["final_event"] is None:
        st.markdown("---")
        st.subheader("Validation humaine requise")
        col_a, col_b = st.columns(2)
        approve = col_a.button(
            "Approuver", type="primary", use_container_width=True, key=f"agent_approve_{run_key}"
        )
        reject = col_b.button(
            "Rejeter", use_container_width=True, key=f"agent_reject_{run_key}"
        )

        if approve or reject:
            try:
                with st.spinner("Analyse en cours..."):
                    progress = st.empty()
                    graph = build_agent_graph(checkpoint_path=run["checkpoint_path"])
                    config = {"configurable": {"thread_id": run["thread_id"]}}
                    graph.update_state(config, {"approval_received": approve})
                    final_event = {}
                    for event in graph.stream(None, config=config, stream_mode="values"):
                        final_event = event
                        _show_step_progress(progress, event)
                    progress.empty()
            except UserFacingError as e:
                severity = getattr(e, "severity", "error")
                retry_hint = (
                    " Réessaie en cliquant à nouveau sur Approuver/Rejeter une fois le "
                    "quota rétabli." if severity == "warning" else ""
                )
                render_user_facing_error(
                    f"{getattr(e, 'user_message', str(e))}{retry_hint}",
                    getattr(e, "technical_detail", None),
                    severity,
                )
                return
            except Exception as e:
                st.error(
                    f"L'analyse a échoué de façon inattendue : {e}\n\n"
                    "Réessaie en cliquant à nouveau sur Approuver/Rejeter."
                )
                return
            run["final_event"] = final_event
            runs[run_key] = run
            st.rerun()
        return

    final = run["final_event"]
    if final.get("errors"):
        st.error(f"Analyse rejetée ou en erreur : {', '.join(final['errors'])}")
    else:
        st.success("Analyse terminée.")

        weekly = final.get("weekly_retention") or {}
        if weekly.get("data"):
            st.subheader(weekly.get("label", "Résultat"))
            st.markdown(weekly["data"])

        driver_analysis = final.get("driver_analysis") or []
        if driver_analysis:
            st.subheader("Facteurs explicatifs")
            for d in driver_analysis:
                with st.expander(d["dimension"]):
                    if "error" in d:
                        st.error(d["error"])
                    elif "skipped" in d:
                        st.info(d["skipped"])
                    else:
                        st.markdown(d["result"])

        checks = final.get("validation_checks") or {}
        if checks:
            st.subheader("Validation")
            for check_name, check in checks.items():
                status = "OK" if check.get("passed") else "ÉCHEC"
                with st.expander(f"{check_name.replace('_', ' ').capitalize()} — {status}"):
                    st.markdown(str(check.get("result")))

        recommendations = final.get("recommendations") or []
        if recommendations:
            st.subheader("Recommandations")
            for i, rec in enumerate(recommendations, 1):
                with st.container(border=True):
                    st.markdown(f"**{i}. {rec.get('title', 'Sans titre')}**")
                    st.write(rec.get("description", ""))
                    m1, m2, m3 = st.columns(3)
                    m1.write(f"**Impact**\n\n{str(rec.get('impact', 'N/A')).capitalize()}")
                    m2.write(f"**Faisabilité**\n\n{str(rec.get('feasibility', 'N/A')).capitalize()}")
                    m3.write(f"**Délai**\n\n{str(rec.get('timeline', 'N/A')).capitalize()}")

        excel_path = final.get("excel_path")
        presentation_path = final.get("presentation_path")

        # Les données nettoyées sont régénérées à la demande (pas par
        # export_node, qui ne produit que le rapport d'analyse) et mises en
        # cache dans `run` pour ne pas relire/reconstruire le classeur à
        # chaque réexécution du script Streamlit tant que ce run est affiché.
        cleaned_bytes = run.get("cleaned_data_excel")
        if cleaned_bytes is None and meta.get("table_name"):
            try:
                cleaned_df = fetch_dataframe(
                    f"SELECT * FROM {quote_ident(meta['table_name'])}", db_path=meta.get("db_path"),
                )
                cleaned_gen = ExcelGenerator()
                cleaned_gen.add_cleaned_data(cleaned_df, title="Données nettoyées")
                cleaned_bytes = cleaned_gen.to_bytes()
                run["cleaned_data_excel"] = cleaned_bytes
            except Exception:
                cleaned_bytes = None

        if excel_path or presentation_path or cleaned_bytes:
            st.markdown("---")
            st.subheader("Livrables")
            d1, d2, d3 = st.columns(3)
            if excel_path and os.path.exists(excel_path):
                with open(excel_path, "rb") as f:
                    d1.download_button(
                        "Télécharger le rapport Excel",
                        f.read(),
                        file_name=os.path.basename(excel_path),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key=f"agent_dl_xlsx_{run_key}",
                    )
            if presentation_path and os.path.exists(presentation_path):
                with open(presentation_path, "rb") as f:
                    d2.download_button(
                        "Télécharger la présentation PowerPoint",
                        f.read(),
                        file_name=os.path.basename(presentation_path),
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        use_container_width=True,
                        key=f"agent_dl_pptx_{run_key}",
                    )
            if cleaned_bytes:
                d3.download_button(
                    "Télécharger les données nettoyées (Excel)",
                    cleaned_bytes,
                    file_name="donnees_nettoyees.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key=f"agent_dl_cleaned_{run_key}",
                )

        _render_results_chat(run_key, run, values, final, llm_provider)

    if st.button("Nouvelle analyse (agent)", key=f"agent_reset_{run_key}"):
        del runs[run_key]
        st.rerun()


def _build_analysis_context(values: dict, final: dict) -> str:
    """Résume l'analyse déjà réalisée pour le prompt de l'assistant conversationnel.

    Pas besoin de tout redonner en détail (les tableaux complets sont déjà
    dans la table DuckDB, interrogeable par l'assistant) -- juste de quoi
    situer la conversation : ce qui a été demandé, calculé, et recommandé.
    """
    lines = [
        f"Question posée à l'agent : {values.get('business_question')}",
        f"Métrique : {values.get('metric_definition') or 'non définie'}",
    ]
    weekly = final.get("weekly_retention") or {}
    if weekly.get("label"):
        lines.append(f"Résultat construit : {weekly['label']}")

    stats = final.get("statistical_tests") or {}
    significant = [dim for dim, s in stats.items() if s.get("significant")]
    if significant:
        lines.append(f"Dimensions statistiquement significatives (chi², p < 0.05) : {', '.join(significant)}")

    recommendations = final.get("recommendations") or []
    if recommendations:
        titles = "; ".join(r.get("title", "") for r in recommendations)
        lines.append(f"Recommandations formulées : {titles}")

    return "\n".join(lines)


def _render_results_chat(run_key: str, run: dict, values: dict, final: dict, llm_provider: str):
    """
    Chat de suivi sur une analyse terminée : contrairement à un simple
    résumé statique, l'assistant peut exécuter de vraies requêtes sur la
    table DuckDB de l'analyse (voir agent.tools.chat_assistant) pour
    répondre à des questions qui n'ont pas déjà de réponse toute prête.

    L'historique vit dans run["chat_history"] (donc dans st.session_state,
    via `runs`) pour survivre aux réexécutions du script -- isolé par
    run_key comme le reste de l'état d'une analyse.
    """
    st.markdown("---")
    st.subheader("Des questions sur ces résultats ?")

    history = run.setdefault("chat_history", [])
    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sql"):
                with st.expander("Requête SQL utilisée"):
                    st.code(msg["sql"], language="sql")

    question = st.chat_input("Ex. : quelle plateforme a le plus baissé ?", key=f"chat_input_{run_key}")
    if not question:
        return

    history.append({"role": "user", "content": question})
    meta = values.get("data_metadata") or {}

    try:
        with st.spinner("Réflexion en cours..."):
            result = answer_question(
                question=question,
                table_name=meta.get("table_name"),
                schema=meta.get("schema", []),
                analysis_context=_build_analysis_context(values, final),
                history=history[:-1],
                db_path=meta.get("db_path"),
                llm_provider=llm_provider,
            )
    except UserFacingError as e:
        history.pop()  # ne pas garder une question sans réponse dans l'historique
        render_user_facing_error(e.user_message, e.technical_detail, e.severity)
        return
    except Exception as e:
        history.pop()
        st.error(f"La question n'a pas pu être traitée : {e}")
        return

    history.append({"role": "assistant", "content": result["answer"], "sql": result.get("sql")})
    # Cap arbitraire : une conversation très longue n'apporte plus rien au
    # contexte (voir MAX_HISTORY_TURNS côté prompt) et grossirait la session
    # indéfiniment. `run` est le même objet que celui stocké dans `runs`
    # (mutation en place), pas besoin de le réassigner explicitement.
    run["chat_history"] = history[-40:]
    st.rerun()
