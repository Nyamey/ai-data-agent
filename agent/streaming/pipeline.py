# agent/streaming/pipeline.py — Pipeline complet d'analyse en streaming
import shutil
import uuid
from pathlib import Path
import duckdb
from agent.streaming.watcher import start_watching
from agent.streaming.anomaly_detector import AnomalyDetector


class StreamingAnalysisPipeline:
    """
    Pipeline qui surveille un dossier et déclenche une analyse agent quand
    l'arrivée d'un nouveau fichier est jugée anormale (volumétrie inhabituelle
    par rapport à l'historique récent des fichiers reçus via `AnomalyDetector`)
    -- au lieu de lancer une analyse coûteuse à chaque fichier, peu importe
    s'il ressemble aux précédents.

    Le graphe de l'agent s'interrompt réellement avant l'étape d'approbation
    (voir agent/graph.py) -- impossible à recueillir de façon interactive
    depuis un thread de surveillance de fichiers. Deux modes explicites :

    - `require_approval=False` (par défaut) : contourne l'approbation
      automatiquement (`approval_received=True`) dès que le graphe s'y
      arrête, pour un pipeline vraiment non supervisé.
    - `require_approval=True` : laisse l'analyse en attente dans
      `self.pending` -- un appelant externe doit ensuite appeler
      `approve(thread_id)` ou `reject(thread_id)` pour la faire reprendre.
    """

    def __init__(
        self,
        watch_dir: str = "./data/stream",
        require_approval: bool = False,
        db_path: str = None,
        checkpoint_path: str = None,
        anomaly_window: int = 12,
        anomaly_threshold: float = 2.0,
        deliverables_dir: str = "./outputs/stream",
    ):
        self.watch_dir = watch_dir
        self.require_approval = require_approval
        self.db_path = db_path or "./data/stream_analytics.duckdb"
        self.checkpoint_path = checkpoint_path or "./data/stream_memory.db"
        self.deliverables_dir = deliverables_dir
        self.detector = AnomalyDetector(window_size=anomaly_window, threshold=anomaly_threshold)
        self.pending = {}  # thread_id -> {"graph", "config", "file_path"}
        Path(watch_dir).mkdir(parents=True, exist_ok=True)

    def _row_count(self, file_path: str) -> int:
        """Compte les lignes du fichier sans le charger entièrement en mémoire."""
        con = duckdb.connect(":memory:")
        try:
            return con.execute(f"SELECT COUNT(*) FROM read_csv_auto('{file_path}')").fetchone()[0]
        finally:
            con.close()

    def _report_deliverables(self, source_file_path: str, final_state: dict):
        """
        Rend visibles les livrables Excel/PPTX d'une analyse déclenchée par le streaming.

        export_node (agent/nodes/export.py) génère déjà ces fichiers pour
        n'importe quel appelant du graphe (CLI, Streamlit, ici) sous
        `./outputs/rapport_<horodatage>.xlsx` -- mais ce nom générique ne dit
        pas quel fichier source a déclenché l'analyse, et rien ne le
        signalait jusqu'ici à qui pilote le pipeline de streaming. On copie
        donc les livrables dans un dossier dédié, nommés d'après le fichier
        source, et on l'annonce -- sans changer export_node lui-même, qui
        reste indépendant de son appelant.
        """
        excel_path = final_state.get("excel_path")
        presentation_path = final_state.get("presentation_path")
        if not excel_path and not presentation_path:
            return

        stem = Path(source_file_path).stem
        dest_dir = Path(self.deliverables_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        for src in filter(None, [excel_path, presentation_path]):
            src_path = Path(src)
            dest_path = dest_dir / f"{stem}_{src_path.name}"
            shutil.copy2(src_path, dest_path)
            print(f"[PIPELINE] Livrable disponible : {dest_path}")

    def on_new_data(self, file_path: str):
        """Callback appelé quand un nouveau fichier arrive."""
        print(f"\n{'=' * 60}")
        print(f"[PIPELINE] Nouveau fichier : {file_path}")

        try:
            row_count = self._row_count(file_path)
        except Exception as e:
            print(f"[PIPELINE] Impossible de lire {file_path} ({e}) -- ignoré.")
            return

        result = self.detector.update(row_count)
        # On lance quand même l'analyse tant que le détecteur n'a pas assez
        # d'historique pour juger (les toutes premières arrivées). En
        # revanche "pas_de_variance" signifie que cette valeur est identique
        # à un historique déjà constant -- par construction le cas le plus
        # normal qui soit, donc à ignorer comme n'importe quelle volumétrie
        # non anormale, pas à traiter comme un cas particulier à lancer.
        should_run = result["anomaly"] or result.get("reason") == "pas_assez_de_donnees"
        if not should_run:
            print(
                f"[PIPELINE] Volumétrie normale ({row_count} lignes, "
                f"z-score {result.get('z_score')}) -- analyse non déclenchée."
            )
            return
        print(f"[PIPELINE] Déclenchement de l'analyse -- {result}")

        from agent.graph import build_agent_graph
        from agent.state import AgentState

        thread_id = f"stream-{Path(file_path).stem}-{uuid.uuid4().hex[:8]}"
        graph = build_agent_graph(checkpoint_path=self.checkpoint_path)
        state = AgentState(
            query=f"Analyse automatique des données du fichier {Path(file_path).name}. "
                  f"Identifie les tendances et anomalies.",
            data_path=file_path,
            db_path=self.db_path,
            output_language="fr",
        )
        config = {"configurable": {"thread_id": thread_id}}

        for event in graph.stream(state, config=config, stream_mode="values"):
            print(f"  [Statut : {event['status']}]")

        snapshot = graph.get_state(config)
        if snapshot.next == ("approval",):
            if self.require_approval:
                self.pending[thread_id] = {"graph": graph, "config": config, "file_path": file_path}
                print(
                    f"[PIPELINE] En attente d'approbation humaine (thread {thread_id}). "
                    f"Appelez pipeline.approve('{thread_id}') ou .reject('{thread_id}')."
                )
                return
            print("[PIPELINE] require_approval=False : approbation automatique.")
            graph.update_state(config, {"approval_received": True})
            for event in graph.stream(None, config=config, stream_mode="values"):
                print(f"  [Statut : {event['status']}]")

        final = graph.get_state(config).values
        print(f"[PIPELINE] Analyse terminée avec le statut : {final.get('status')}")
        self._report_deliverables(file_path, final)

    def approve(self, thread_id: str) -> dict:
        """Approuve une analyse en attente (mode require_approval=True)."""
        return self._resume(thread_id, approved=True)

    def reject(self, thread_id: str) -> dict:
        """Rejette une analyse en attente (mode require_approval=True)."""
        return self._resume(thread_id, approved=False)

    def _resume(self, thread_id: str, approved: bool) -> dict:
        pending = self.pending.pop(thread_id, None)
        if not pending:
            raise KeyError(f"Aucune analyse en attente pour le thread {thread_id}")
        graph, config = pending["graph"], pending["config"]
        graph.update_state(config, {"approval_received": approved})
        for event in graph.stream(None, config=config, stream_mode="values"):
            print(f"  [Statut : {event['status']}]")
        final = graph.get_state(config).values
        print(f"[PIPELINE] Analyse terminée avec le statut : {final.get('status')}")
        self._report_deliverables(pending["file_path"], final)
        return final

    def start(self):
        """Démarre le pipeline de streaming."""
        start_watching(self.watch_dir, self.on_new_data)


if __name__ == "__main__":
    pipeline = StreamingAnalysisPipeline()
    pipeline.start()
