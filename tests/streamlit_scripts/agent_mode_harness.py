# Script exécuté par AppTest (tests/test_app_integration.py) : reproduit ce
# que app.py fait pour le mode agent, sans passer par st.file_uploader (non
# simulable par AppTest). Les fichiers/paramètres viennent de variables
# d'environnement pour que le test appelant (même process, voir
# test_app_integration.py) puisse les faire varier sans réécrire ce script.
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from agent_ui import render_agent_mode

csv_paths = os.environ["HARNESS_CSV_PATHS"].split(os.pathsep)
cleaned_files = [(os.path.basename(p), pd.read_csv(p)) for p in csv_paths]
query = os.environ.get("HARNESS_QUERY", "Question de test")
provider = os.environ.get("HARNESS_PROVIDER", "Groq (Recommandé)")
current_source = (tuple(sorted((n, len(d)) for n, d in cleaned_files)), provider, query)

render_agent_mode(cleaned_files, query, provider, current_source)
