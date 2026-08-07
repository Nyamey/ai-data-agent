# agent/streaming/watcher.py — Surveillance de répertoire pour nouveaux fichiers
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class DataFileHandler(FileSystemEventHandler):
    """
    Détecte l'arrivée de nouveaux fichiers de données et déclenche l'agent.
    """
    
    def __init__(self, agent_callback, watch_extensions=None):
        self.agent_callback = agent_callback
        self.watch_extensions = watch_extensions or [".csv", ".parquet", ".json"]
    
    def on_created(self, event):
        """Appelé automatiquement quand un fichier est créé dans le dossier surveillé."""
        if not event.is_directory:
            ext = Path(event.src_path).suffix.lower()
            if ext in self.watch_extensions:
                print(f"\n[STREAMING] Nouveau fichier détecté : {event.src_path}")
                self.agent_callback(event.src_path)


def start_watching(watch_dir: str, agent_callback):
    """
    Démarre la surveillance d'un répertoire.
    
    Args:
        watch_dir: Dossier à surveiller
        agent_callback: Fonction à appeler quand un nouveau fichier arrive
    """
    # S'assurer que le dossier existe
    Path(watch_dir).mkdir(parents=True, exist_ok=True)
    
    observer = Observer()
    handler = DataFileHandler(agent_callback)
    observer.schedule(handler, watch_dir, recursive=False)
    observer.start()
    
    print(f"[STREAMING] Surveillance de {watch_dir} active...")
    print(f"  Extensions surveillées : {handler.watch_extensions}")
    print(f"  Place un fichier CSV dans ce dossier pour déclencher une analyse.")
    print(f"  Appuie sur Ctrl+C pour arrêter.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\n[STREAMING] Surveillance arrêtée.")
    observer.join()
