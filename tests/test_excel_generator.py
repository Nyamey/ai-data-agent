# tests/test_excel_generator.py — Génération de classeurs Excel
import openpyxl
import pandas as pd

from agent.output.excel_generator import ExcelGenerator


def test_add_weekly_retention_creates_sheet_with_data(tmp_path):
    gen = ExcelGenerator()
    df = pd.DataFrame({"semaine": ["2024-01-01", "2024-01-08"], "valeur": [10, 12]})
    gen.add_weekly_retention(df, title="Rétention")
    path = str(tmp_path / "out.xlsx")
    gen.save(path)

    wb = openpyxl.load_workbook(path)
    assert "Rétention" in wb.sheetnames
    assert "Sheet" not in wb.sheetnames


def test_sheet_titles_are_deduplicated(tmp_path):
    gen = ExcelGenerator()
    df = pd.DataFrame({"a": [1], "b": [2]})
    gen.add_driver_analysis(df, title="Facteur - plateforme")
    gen.add_driver_analysis(df, title="Facteur - plateforme")
    path = str(tmp_path / "out.xlsx")
    gen.save(path)

    wb = openpyxl.load_workbook(path)
    sheets = [s for s in wb.sheetnames if s != "Sheet"]
    assert len(sheets) == 2
    assert len(set(sheets)) == 2


def test_sheet_title_truncated_to_excel_limit(tmp_path):
    gen = ExcelGenerator()
    df = pd.DataFrame({"a": [1]})
    long_title = "Facteur - " + "x" * 50
    gen.add_driver_analysis(df, title=long_title)
    path = str(tmp_path / "out.xlsx")
    gen.save(path)

    wb = openpyxl.load_workbook(path)
    sheets = [s for s in wb.sheetnames if s != "Sheet"]
    assert all(len(s) <= 31 for s in sheets)


def test_add_validation_checks_reports_pass_fail(tmp_path):
    gen = ExcelGenerator()
    gen.add_validation_checks({
        "doublons": {"result": 0, "passed": True},
        "plage_dates": {"result": "erreur", "passed": False},
    })
    path = str(tmp_path / "out.xlsx")
    gen.save(path)

    wb = openpyxl.load_workbook(path)
    ws = wb["Validation"]
    rows = list(ws.iter_rows(values_only=True))
    statuses = {r[0]: r[2] for r in rows[1:]}
    assert statuses["doublons"] == "OK"
    assert statuses["plage_dates"] == "ÉCHEC"
