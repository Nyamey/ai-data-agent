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


@pytest.fixture
def sample_joinable_csvs(tmp_path):
    """Trois fichiers liés (commandes/clients/produits) pour tester load_joined_data().

    commandes est la racine ; clients et produits s'y rattachent chacun --
    un arbre de jointure à 3 fichiers, pas juste 2.
    """
    commandes = pd.DataFrame({
        "id": range(1, 41),
        "client_id_ref": [(i % 10) + 1 for i in range(40)],
        "produit_id_ref": [(i % 5) + 1 for i in range(40)],
        "date_commande": ["2024-01-0" + str((i % 9) + 1) for i in range(40)],
        "montant": range(40),
    })
    clients = pd.DataFrame({
        "id": range(1, 11),
        "nom": [f"Client{i}" for i in range(1, 11)],
        "segment": (["premium", "standard"] * 5),
    })
    produits = pd.DataFrame({
        "id": range(1, 6),
        "categorie": (["A", "B"] * 3)[:5],
    })

    commandes_path = tmp_path / "commandes.csv"
    clients_path = tmp_path / "clients.csv"
    produits_path = tmp_path / "produits.csv"
    commandes.to_csv(commandes_path, index=False)
    clients.to_csv(clients_path, index=False)
    produits.to_csv(produits_path, index=False)

    return {
        "commandes": str(commandes_path),
        "clients": str(clients_path),
        "produits": str(produits_path),
    }
