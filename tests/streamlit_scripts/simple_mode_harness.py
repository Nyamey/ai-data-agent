# Script exécuté par AppTest (tests/test_app_integration.py) : reproduit ce
# que app.py fait pour le mode simple, sans passer par st.file_uploader.
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from app_utils import clean_data
from simple_mode_ui import render_simple_mode

csv_paths = os.environ["HARNESS_CSV_PATHS"].split(os.pathsep)
cleaned_files = []
describe_list = []
for path in csv_paths:
    raw = pd.read_csv(path)
    cleaned, _ = clean_data(raw)
    cleaned_files.append((os.path.basename(path), cleaned))
    describe_list.append(cleaned.describe())

query = os.environ.get("HARNESS_QUERY", "Question de test")
provider = os.environ.get("HARNESS_PROVIDER", "Groq (Recommandé)")
current_source = (tuple(sorted((n, len(d)) for n, d in cleaned_files)), provider, query)

st.session_state.setdefault("history", [])
if "harness_triggered" not in st.session_state:
    st.session_state["harness_triggered"] = True
    st.session_state["analyze"] = True

render_simple_mode(cleaned_files, describe_list, query, provider, current_source)
