# agent/state.py — Schéma d'état de l'agent
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class AnalysisStatus(str, Enum):
    """Statuts possibles de l'analyse."""
    PENDING = "en_attente"
    FRAMING = "cadrage"
    INSPECTION = "inspection"
    AWAITING_APPROVAL = "en_attente_approbation"
    BUILDING = "construction"
    TESTING = "test"
    VALIDATING = "validation"
    RECOMMENDING = "recommandations"
    EXPORTING = "export"
    COMPLETED = "termine"
    FAILED = "echec"


class AgentState(BaseModel):
    """
    État global de l'agent d'analyse de données.
    
    Ce schéma voyage à travers toutes les étapes du graphe.
    Chaque nœud lit certains champs et en met à jour d'autres.
    """
    
    # --- Entrées ---
    query: str = Field(description="La question commerciale à résoudre")
    data_path: str = Field(description="Chemin vers le fichier de données")
    output_language: str = Field(default="fr", description="Langue des livrables")
    db_path: Optional[str] = Field(
        default=None,
        description="Chemin DuckDB à utiliser (par défaut DUCKDB_PATH) -- "
        "permet d'isoler les analyses concurrentes (ex. sessions Streamlit)",
    )
    llm_provider: Optional[str] = Field(
        default=None,
        description="Provider LLM à utiliser (par défaut DEFAULT_LLM_PROVIDER)",
    )
    
    # --- État de progression ---
    status: AnalysisStatus = Field(default=AnalysisStatus.PENDING)
    iterations: int = Field(default=0, description="Nombre d'itérations")
    max_iterations: int = Field(default=3, description="Maximum d'itérations")
    
    # --- Résultats du cadrage ---
    metric_definition: Optional[str] = None
    business_question: Optional[str] = None
    comparison_period: Optional[str] = None
    assumptions: list[str] = Field(default_factory=list)
    
    # --- Résultats de l'inspection ---
    data_metadata: Optional[dict] = None
    needs_aggregation: Optional[bool] = None
    approval_received: Optional[bool] = None
    
    # --- Résultats de construction ---
    weekly_retention: Optional[dict] = None
    cohort_analysis: Optional[dict] = None
    
    # --- Résultats des tests ---
    driver_analysis: Optional[list[dict]] = None
    statistical_tests: Optional[dict] = None
    
    # --- Résultats de validation ---
    validation_checks: Optional[dict] = None
    audit_trail: list[str] = Field(default_factory=list)
    
    # --- Recommandations ---
    recommendations: Optional[list[dict]] = None
    
    # --- Livrables ---
    excel_path: Optional[str] = None
    presentation_path: Optional[str] = None
    
    # --- Erreurs ---
    errors: list[str] = Field(default_factory=list)
