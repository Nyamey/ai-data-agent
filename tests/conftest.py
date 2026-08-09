# tests/conftest.py — fixtures partagées
import io

import pandas as pd
import pytest


class FakeUploadedFile(io.BytesIO):
    """Reproduit st.UploadedFile, qui hérite réellement de io.BytesIO.

    Un simple duck-type seek()/read() ne suffit pas : le moteur C de pandas
    utilise un chemin différent (et ignore le paramètre `encoding` demandé)
    face à un objet qui n'expose pas toute la surface d'un vrai fichier
    binaire, ce qui fausserait le test de repli d'encodage ci-dessous.
    """


@pytest.fixture
def fake_upload():
    return FakeUploadedFile


@pytest.fixture
def sample_retention_csv(tmp_path):
    """Petit CSV rétention (id + date + dimensions catégorielles), sans valeurs manquantes."""
    df = pd.DataFrame({
        "customer_id": range(1, 41),
        "activity_date": (["2024-01-01"] * 10 + ["2024-01-08"] * 10
                           + ["2024-01-15"] * 10 + ["2024-01-22"] * 10),
        "platform": (["web", "mobile"] * 20),
        "region": (["EU", "US", "APAC", "EU"] * 10),
    })
    path = tmp_path / "retention.csv"
    df.to_csv(path, index=False)
    return str(path)


@pytest.fixture
def sample_no_id_csv(tmp_path):
    """CSV sans colonne identifiant ni colonne date, pour tester le repli COUNT(*)."""
    df = pd.DataFrame({
        "produit": ["A", "B", "C", "D"] * 10,
        "prix": list(range(40)),
        "region": ["Nord", "Sud"] * 20,
    })
    path = tmp_path / "produits.csv"
    df.to_csv(path, index=False)
    return str(path)
