# tests/test_app_utils.py — Fonctions pures de app.py (nettoyage, exports, sécurité)
import pandas as pd

from app_utils import (
    build_csv_export,
    build_excel_report,
    build_markdown_report,
    build_pptx_report,
    clean_data,
    neutralize_formulas,
    read_csv_robust,
    sanitize_sheet_name,
)


def test_read_csv_robust_detects_semicolon_and_utf8_sig(fake_upload):
    raw = "id;nom;ville\n1;Alice;Paris\n2;Bob;Lyon\n".encode("utf-8-sig")
    df, enc = read_csv_robust(fake_upload(raw))
    assert enc == "utf-8-sig"
    assert list(df.columns) == ["id", "nom", "ville"]
    assert len(df) == 2


def test_read_csv_robust_detects_comma(fake_upload):
    raw = "id,nom\n1,Alice\n2,Bob\n".encode("utf-8")
    df, enc = read_csv_robust(fake_upload(raw))
    assert list(df.columns) == ["id", "nom"]


def test_read_csv_robust_falls_back_to_latin1(fake_upload):
    # "Café" encodé en latin-1 n'est pas un utf-8 valide : la lecture doit
    # retomber sur latin-1 plutôt qu'échouer.
    raw = "ville\nCafé\n".encode("latin-1")
    df, enc = read_csv_robust(fake_upload(raw))
    assert enc == "latin-1"
    assert df["ville"].iloc[0] == "Café"


def test_clean_data_preserves_leading_zeros():
    df = pd.DataFrame({"code_postal": ["00501", "00502", "00503"]})
    cleaned, report = clean_data(df)
    assert cleaned["code_postal"].tolist() == ["00501", "00502", "00503"]
    assert "code_postal" not in report["columns_converted_numeric"]


def test_clean_data_converts_genuine_numeric_column():
    df = pd.DataFrame({"prix": ["10", "20", "30"]})
    cleaned, report = clean_data(df)
    assert report["columns_converted_numeric"] == ["prix"]
    assert cleaned["prix"].tolist() == [10, 20, 30]


def test_clean_data_converts_french_decimal_notation():
    df = pd.DataFrame({"montant": ["120,50", "80,00", "15,25"]})
    cleaned, report = clean_data(df)
    assert "montant" in report["columns_converted_decimal"]
    assert cleaned["montant"].tolist() == [120.50, 80.00, 15.25]


def test_clean_data_parses_iso_dates_without_day_month_confusion():
    # Régression : format="mixed", dayfirst=True inverse jour/mois même sur
    # des dates ISO non ambiguës dès que le jour est <= 12.
    df = pd.DataFrame({"date_signup": ["2024-01-05", "2024-02-09", "2024-03-11"]})
    cleaned, report = clean_data(df)
    assert "date_signup" in report["columns_converted_date"]
    assert cleaned["date_signup"].iloc[0] == pd.Timestamp("2024-01-05")
    assert cleaned["date_signup"].iloc[1] == pd.Timestamp("2024-02-09")


def test_clean_data_removes_duplicates_and_empty_rows():
    df = pd.DataFrame({
        "a": [1, 1, 2, None],
        "b": ["x", "x", "y", None],
    })
    cleaned, report = clean_data(df)
    assert report["duplicates_removed"] == 1
    assert report["empty_rows_removed"] == 1
    assert report["final_rows"] == 2


def test_clean_data_strips_whitespace_and_blank_to_nan():
    df = pd.DataFrame({"nom": ["  Alice  ", "", "Bob"]})
    cleaned, report = clean_data(df)
    assert cleaned["nom"].iloc[0] == "Alice"
    assert pd.isna(cleaned["nom"].iloc[1])


def test_neutralize_formulas_prefixes_dangerous_cells():
    df = pd.DataFrame({"nom": ["=HYPERLINK(\"http://evil\")", "+1+1", "@cmd", "Alice"]})
    out = neutralize_formulas(df)
    assert out["nom"].iloc[0].startswith("'=")
    assert out["nom"].iloc[1].startswith("'+")
    assert out["nom"].iloc[2].startswith("'@")
    assert out["nom"].iloc[3] == "Alice"


def test_sanitize_sheet_name_truncates_and_dedupes():
    used = set()
    name1 = sanitize_sheet_name("a" * 40 + ".csv", used)
    name2 = sanitize_sheet_name("a" * 40 + ".csv", used)
    assert len(name1) <= 31
    assert name1 != name2


def test_sanitize_sheet_name_strips_invalid_excel_chars():
    used = set()
    name = sanitize_sheet_name("rapport:ventes/2024.csv", used)
    assert not any(c in name for c in ":\\/?*[]")


def test_sanitize_sheet_name_never_empty():
    used = set()
    name = sanitize_sheet_name(":::.csv", used)
    assert name


def test_build_markdown_report_contains_key_sections():
    md = build_markdown_report(
        "Quelle est la tendance ?", "groq/llama", [("f.csv", pd.DataFrame({"a": [1]}))],
        "Voici l'analyse.", "2026-08-09 12:00",
    )
    assert "Quelle est la tendance ?" in md
    assert "groq/llama" in md
    assert "f.csv" in md
    assert "Voici l'analyse." in md


def test_build_excel_report_produces_valid_workbook():
    files = [("f1.csv", pd.DataFrame({"a": [1, 2]})), ("f2.csv", pd.DataFrame({"b": [3, 4]}))]
    data = build_excel_report(files, "question", "model", "analyse")
    assert data[:2] == b"PK"  # signature ZIP (xlsx est une archive ZIP)
    assert len(data) > 0


def test_build_csv_export_single_file_returns_csv():
    data, name, mime = build_csv_export([("f.csv", pd.DataFrame({"a": [1]}))])
    assert name == "donnees_nettoyees.csv"
    assert mime == "text/csv"


def test_build_csv_export_multiple_files_returns_zip_with_unique_names():
    files = [("dup.csv", pd.DataFrame({"a": [1]})), ("dup.csv", pd.DataFrame({"a": [2]}))]
    data, name, mime = build_csv_export(files)
    assert name == "donnees_nettoyees.zip"
    assert mime == "application/zip"
    import zipfile
    import io as _io
    with zipfile.ZipFile(_io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert len(names) == 2
        assert len(set(n.lower() for n in names)) == 2  # pas de collision silencieuse


def test_build_csv_export_strips_path_components_from_filename():
    # Un nom de fichier téléversé n'est pas garanti sans composant de
    # chemin (client non-navigateur, en-tête forgé) : l'entrée ZIP ne doit
    # jamais pouvoir désigner un chemin hors du dossier d'extraction.
    files = [
        ("../../evil.csv", pd.DataFrame({"a": [1]})),
        ("../../evil.csv", pd.DataFrame({"a": [2]})),
    ]
    import zipfile
    import io as _io
    data, _, _ = build_csv_export(files)
    with zipfile.ZipFile(_io.BytesIO(data)) as zf:
        for entry_name in zf.namelist():
            assert ".." not in entry_name
            assert "/" not in entry_name and "\\" not in entry_name


def test_build_pptx_report_produces_valid_deck():
    files = [("f.csv", pd.DataFrame({"a": [1]}))]
    data = build_pptx_report("question", "model", files, "Longue analyse. " * 100, "2026-08-09")
    assert data[:2] == b"PK"  # signature ZIP (pptx est une archive ZIP)
    assert len(data) > 0
