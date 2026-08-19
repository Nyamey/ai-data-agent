# tests/test_watcher.py : détection de nouveaux fichiers (watchdog)
#
# start_watching() (boucle infinie + gestion de Ctrl+C) n'est pas testée --
# trop coûteuse à vérifier utilement sans threading réel. DataFileHandler.
# on_created(), la logique qui décide quels événements déclenchent le
# callback, l'est directement.
from types import SimpleNamespace

from agent.streaming.watcher import DataFileHandler


def _event(src_path, is_directory=False):
    return SimpleNamespace(src_path=src_path, is_directory=is_directory)


def test_on_created_triggers_callback_for_watched_extension():
    calls = []
    handler = DataFileHandler(agent_callback=calls.append)

    handler.on_created(_event("/data/stream/ventes.csv"))

    assert calls == ["/data/stream/ventes.csv"]


def test_on_created_ignores_unwatched_extension():
    calls = []
    handler = DataFileHandler(agent_callback=calls.append)

    handler.on_created(_event("/data/stream/notes.txt"))

    assert calls == []


def test_on_created_ignores_directories():
    calls = []
    handler = DataFileHandler(agent_callback=calls.append)

    handler.on_created(_event("/data/stream/sous_dossier.csv", is_directory=True))

    assert calls == []


def test_on_created_respects_custom_extensions():
    calls = []
    handler = DataFileHandler(agent_callback=calls.append, watch_extensions=[".xlsx"])

    handler.on_created(_event("/data/stream/rapport.xlsx"))
    handler.on_created(_event("/data/stream/donnees.csv"))  # plus dans la liste personnalisée

    assert calls == ["/data/stream/rapport.xlsx"]


def test_on_created_extension_match_is_case_insensitive():
    calls = []
    handler = DataFileHandler(agent_callback=calls.append)

    handler.on_created(_event("/data/stream/VENTES.CSV"))

    assert calls == ["/data/stream/VENTES.CSV"]
