# agent/nodes/test.py — Nœud 4 : Tests des facteurs explicatifs
from scipy import stats as scipy_stats
from agent.state import AgentState, AnalysisStatus
from agent.tools.data_loader import fetch_dataframe, quote_ident


def test_node(state: AgentState) -> dict:
    """
    Nœud 4 : Test.

    Compare la métrique selon les colonnes catégorielles disponibles
    (ex. plateforme, région, segment...). Agnostique au schéma : les
    colonnes exclues (identifiant d'entité, dates) sont celles détectées
    par l'inspection, pas des noms fixes.

    Pour chaque dimension, un test du chi² d'ajustement (H0 : répartition
    uniforme entre catégories) évalue si l'écart observé est statistiquement
    significatif (p < 0.05) ou relève du bruit d'échantillonnage.
    """
    state.status = AnalysisStatus.TESTING

    # table/id_col/colonnes de dimension viennent tous du schéma du CSV
    # téléversé (non fiable) : quote_ident() est requis à chaque
    # interpolation SQL -- voir sa docstring dans agent/tools/data_loader.py.
    table = quote_ident(state.data_metadata.get("table_name", "data"))
    db_path = state.data_metadata.get("db_path")
    id_col = state.data_metadata.get("id_column")
    date_cols = set(state.data_metadata.get("date_range", {}).keys())

    count_expr = f"COUNT(DISTINCT {quote_ident(id_col)})" if id_col else "COUNT(*)"
    count_label = "nb_entites" if id_col else "nb_lignes"

    # Lister les colonnes disponibles
    columns = [s["column_name"] for s in state.data_metadata.get("schema", [])]

    # Pour chaque colonne catégorielle, calculer la métrique par segment
    driver_results = []
    statistical_tests = {}

    excluded = date_cols | ({id_col} if id_col else set())
    dimension_cols = [
        col for col in columns
        if col not in excluded and "date" not in col.lower()
    ]

    for col in dimension_cols[:6]:  # Limiter à 6 colonnes
        query = f"""
            SELECT {quote_ident(col)}, {count_expr} as {count_label}
            FROM {table}
            GROUP BY {quote_ident(col)}
            ORDER BY {count_label} DESC
        """
        try:
            df = fetch_dataframe(query, db_path=db_path)
            entry = {"dimension": col, "result": df.to_markdown(index=False), "query": query}

            # Test du chi² : il faut au moins 2 catégories et des effectifs
            # non nuls pour que le test soit défini.
            counts = df[count_label].dropna()
            if len(counts) >= 2 and counts.sum() > 0:
                chi2, p_value = scipy_stats.chisquare(counts.to_numpy())
                significant = bool(p_value < 0.05)
                stat = {
                    "chi2": round(float(chi2), 3),
                    "p_value": round(float(p_value), 4),
                    "significant": significant,
                    "n_categories": int(len(counts)),
                }
                entry.update(stat)
                statistical_tests[col] = stat

            driver_results.append(entry)
        except Exception as e:
            driver_results.append({"dimension": col, "error": str(e)})

    n_significant = sum(1 for s in statistical_tests.values() if s["significant"])
    return {
        "status": AnalysisStatus.VALIDATING,
        "driver_analysis": driver_results,
        "statistical_tests": statistical_tests,
        "audit_trail": state.audit_trail + [
            f"Test : {len(driver_results)} dimensions analysées, "
            f"{n_significant} statistiquement significative(s) (p < 0.05)"
        ],
    }
