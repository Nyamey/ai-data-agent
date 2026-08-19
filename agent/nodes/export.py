# agent/nodes/export.py : nœud 8, export Excel/PowerPoint
from datetime import datetime
from pathlib import Path
from agent.state import AgentState, AnalysisStatus
from agent.tools.data_loader import fetch_dataframe
from agent.output.excel_generator import ExcelGenerator
from agent.output.pptx_generator import PresentationGenerator
from agent.output.consistency_check import verify_consistency


def export_node(state: AgentState) -> dict:
    """
    Nœud 8 : Export.

    Génère les livrables Excel et PowerPoint à partir des résultats réels de
    l'agent. execute_query() (utilisée par build/test pour l'affichage) ne
    renvoie que du markdown, impropre à openpyxl/python-pptx : cette
    étape ré-exécute donc les requêtes conservées par build_node/test_node pour
    obtenir de vrais DataFrames, avant de vérifier la cohérence des deux
    fichiers générés.

    Un échec d'export ne fait pas échouer l'analyse : les recommandations et
    la validation restent le livrable principal, l'export est un bonus.
    """
    state.status = AnalysisStatus.EXPORTING
    db_path = (state.data_metadata or {}).get("db_path")

    try:
        output_dir = Path("./outputs")
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        excel = ExcelGenerator()
        weekly = state.weekly_retention or {}
        if weekly.get("query"):
            df = fetch_dataframe(weekly["query"], db_path=db_path)
            excel.add_weekly_retention(df, title=weekly.get("label") or "Métrique")

        for d in state.driver_analysis or []:
            if d.get("query"):
                df = fetch_dataframe(d["query"], db_path=db_path)
                excel.add_driver_analysis(df, title=f"Facteur - {d['dimension']}")

        excel.add_validation_checks(state.validation_checks or {})
        excel_path = str(output_dir / f"rapport_{stamp}.xlsx")
        excel.save(excel_path)

        findings = [weekly["label"]] if weekly.get("label") else []
        for dim, stat in (state.statistical_tests or {}).items():
            marker = "significatif" if stat.get("significant") else "non significatif"
            findings.append(f"{dim} : p={stat.get('p_value')} ({marker})")
        if not findings:
            findings = ["Aucune observation disponible."]

        pptx = PresentationGenerator()
        pptx_path = str(output_dir / f"presentation_{stamp}.pptx")
        pptx.generate(
            problem=state.business_question or state.query,
            findings=findings,
            validation=state.validation_checks or {},
            recommendations=state.recommendations or [],
            output_path=pptx_path,
        )

        audit = [f"Export : {excel_path}, {pptx_path}"]
        try:
            check = verify_consistency(excel_path, pptx_path)
            audit.append(
                "Export : cohérence Excel/PPTX "
                + ("OK" if check["passed"] else f"écarts détectés ({check['inconsistencies']})")
            )
        except Exception as e:
            audit.append(f"Export : vérification de cohérence non concluante ({e})")

        return {
            "status": AnalysisStatus.COMPLETED,
            "excel_path": excel_path,
            "presentation_path": pptx_path,
            "audit_trail": state.audit_trail + audit,
        }
    except Exception as e:
        return {
            "status": AnalysisStatus.COMPLETED,
            "errors": state.errors + [f"Export Excel/PPTX échoué : {e}"],
            "audit_trail": state.audit_trail + [f"Export : échec ({e})"],
        }
