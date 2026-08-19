# agent/nodes/validate.py : nœud 5, validation
from agent.state import AgentState, AnalysisStatus
from agent.tools.data_loader import execute_query, quote_ident


def validate_node(state: AgentState) -> dict:
    """
    Nœud 5 : Validation.

    Vérifie la cohérence des résultats : rapproche les comptes (entités
    distinctes si une colonne d'identifiant est détectée, sinon nombre de
    lignes), vérifie la plage de dates si une colonne date existe, et
    contrôle les doublons. Agnostique au schéma.
    """
    state.status = AnalysisStatus.VALIDATING

    # table/id_col/colonne de date viennent tous du schéma du CSV téléversé
    # (non fiable) : quote_ident() est requis à chaque interpolation SQL,
    # voir sa docstring dans agent/tools/data_loader.py.
    table = quote_ident(state.data_metadata.get("table_name", "data"))
    db_path = state.data_metadata.get("db_path")
    id_col = state.data_metadata.get("id_column")
    date_cols = list(state.data_metadata.get("date_range", {}).keys())

    checks = {}

    # execute_query() absorbe déjà ses propres exceptions et renvoie une
    # chaîne "Erreur SQL: ..." au lieu de lever : un try/except autour de
    # ses appels ne s'exécuterait donc jamais (code mort, jamais atteint) et
    # masquait en plus un vrai bug : un contrôle marqué "passed": True même
    # quand la requête sous-jacente avait échoué, puisque l'erreur n'était
    # visible que dans le texte du résultat, jamais dans une exception.
    def _passed(result: str) -> bool:
        return not result.startswith("Erreur SQL")

    # Vérification 1 : nombre total d'entités distinctes (ou de lignes)
    if id_col:
        total = execute_query(
            f"SELECT COUNT(DISTINCT {quote_ident(id_col)}) as total FROM {table}", db_path=db_path
        )
        checks["total_entites"] = {"result": total, "passed": _passed(total)}
    else:
        total = execute_query(f"SELECT COUNT(*) as total FROM {table}", db_path=db_path)
        checks["total_lignes"] = {"result": total, "passed": _passed(total)}

    # Vérification 2 : plage de dates (si une colonne date a été détectée)
    if date_cols:
        col = date_cols[0]
        dates = execute_query(
            f"SELECT MIN({quote_ident(col)}), MAX({quote_ident(col)}) FROM {table}", db_path=db_path
        )
        checks["plage_dates"] = {"result": dates, "passed": _passed(dates)}

    # Vérification 3 : doublons
    dup_count = state.data_metadata.get("duplicate_count", 0)
    checks["doublons"] = {"result": dup_count, "passed": dup_count == 0}

    return {
        "status": AnalysisStatus.RECOMMENDING,
        "validation_checks": checks,
        "audit_trail": state.audit_trail + [
            f"Validation : {len(checks)} contrôles effectués, "
            f"{sum(1 for c in checks.values() if c['passed'])} réussis"
        ],
    }
