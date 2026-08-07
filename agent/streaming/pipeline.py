# agent/streaming/pipeline.py — Pipeline complet d'analyse en streaming
import os
from pathlib import Path
from agent.streaming.watcher import start_watching
from agent.streaming.anomaly_detector import AnomalyDetector


class StreamingAnalysisPipeline:
    """
    Pipeline qui surveille un dossier, détecte les anomalies,
    et déclenche automatiquement une analyse quand nécessaire.
    """
    
    def __init__(self, watch_dir: str = "./data/stream"):
        self.watch_dir = watch_dir
        self.detector = AnomalyDetector()
        Path(watch_dir).mkdir(parents=True, exist_ok=True)
    
    def on_new_data(self, file_path: str):
        """Callback appelé quand un nouveau fichier arrive."""
        print(f"\n{'=' * 60}")
        print(f"[PIPELINE] Traitement de {file_path}")
        
        # Importer ici pour éviter les imports circulaires
        from agent.graph import build_agent_graph
        from agent.state import AgentState
        
        # Lancer l'agent d'analyse directement
        # (Dans une version complète, on détecterait d'abord les anomalies)
        agent = build_agent_graph()
        state = AgentState(
            query=f"Analyse automatique des données du fichier {Path(file_path).name}. "
                  f"Identifie les tendances et anomalies.",
            data_path=file_path,
            output_language="fr",
        )
        
        config = {"configurable": {"thread_id": f"stream-{Path(file_path).stem}"}}
        
        for event in agent.stream(state, config=config, stream_mode="values"):
            print(f"  [Statut : {event['status']}]")
        
        print(f"[PIPELINE] Analyse terminée.")
    
    def start(self):
        """Démarre le pipeline de streaming."""
        start_watching(self.watch_dir, self.on_new_data)


if __name__ == "__main__":
    pipeline = StreamingAnalysisPipeline()
    pipeline.start()
