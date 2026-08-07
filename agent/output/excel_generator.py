# agent/output/excel_generator.py — Génération de classeurs Excel
import openpyxl
from openpyxl.chart import LineChart, BarChart, Reference
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils.dataframe import dataframe_to_rows
import pandas as pd


class ExcelGenerator:
    """
    Génère un classeur Excel avec analyses et graphiques.
    
    Onglets générés :
    1. Rétention hebdomadaire
    2. Analyse de cohorte
    3. Analyse des facteurs
    4. Validation
    """
    
    def __init__(self):
        self.wb = openpyxl.Workbook()
        # Style des en-têtes
        self.header_font = Font(bold=True, color="FFFFFF", size=12)
        self.header_fill = PatternFill(start_color="2F5496", end_color="2F5496")
    
    def _add_sheet_with_data(self, title: str, df: pd.DataFrame, chart_type: str = None):
        """Ajoute une feuille avec des données et optionnellement un graphique."""
        ws = self.wb.create_sheet(title=title)
        
        # Ajouter les données
        for row in dataframe_to_rows(df, index=False, header=True):
            ws.append(row)
        
        # Styliser l'en-tête
        for cell in ws[1]:
            cell.font = self.header_font
            cell.fill = self.header_fill
            cell.alignment = Alignment(horizontal="center")
        
        # Auto-largeur des colonnes
        for column in ws.columns:
            max_length = max(len(str(cell.value or "")) for cell in column)
            ws.column_dimensions[column[0].column_letter].width = min(max_length + 2, 30)
        
        # Ajouter un graphique si demandé
        if chart_type == "line" and ws.max_row > 1:
            chart = LineChart()
            chart.title = title
            data = Reference(ws, min_col=2, min_row=1, max_row=ws.max_row, max_col=ws.max_column)
            cats = Reference(ws, min_col=1, min_row=2, max_row=ws.max_row)
            chart.add_data(data, titles_from_data=True)
            chart.set_categories(cats)
            ws.add_chart(chart, f"A{ws.max_row + 3}")
        
        elif chart_type == "bar" and ws.max_row > 1:
            chart = BarChart()
            chart.title = title
            data = Reference(ws, min_col=2, min_row=1, max_row=ws.max_row, max_col=ws.max_column)
            cats = Reference(ws, min_col=1, min_row=2, max_row=ws.max_row)
            chart.add_data(data, titles_from_data=True)
            chart.set_categories(cats)
            ws.add_chart(chart, f"A{ws.max_row + 3}")
    
    def add_weekly_retention(self, df: pd.DataFrame):
        """Ajoute l'onglet rétention hebdomadaire."""
        self._add_sheet_with_data("Rétention Hebdo", df, chart_type="line")
    
    def add_cohort_analysis(self, df: pd.DataFrame):
        """Ajoute l'onglet analyse de cohorte."""
        self._add_sheet_with_data("Analyse Cohorte", df, chart_type="line")
    
    def add_driver_analysis(self, df: pd.DataFrame):
        """Ajoute l'onglet analyse des facteurs."""
        self._add_sheet_with_data("Analyse Facteurs", df, chart_type="bar")
    
    def add_validation_checks(self, checks: dict):
        """Ajoute l'onglet validation."""
        ws = self.wb.create_sheet(title="Validation")
        ws.append(["Contrôle", "Résultat", "Statut"])
        
        for cell in ws[1]:
            cell.font = self.header_font
            cell.fill = self.header_fill
        
        for key, value in checks.items():
            status = "OK" if value.get("passed") else "ÉCHEC"
            ws.append([key, str(value.get("result", "")), status])
    
    def save(self, path: str) -> str:
        """Sauvegarde le classeur et retourne le chemin."""
        # Supprimer la feuille par défaut
        if "Sheet" in self.wb.sheetnames:
            del self.wb["Sheet"]
        self.wb.save(path)
        return path
