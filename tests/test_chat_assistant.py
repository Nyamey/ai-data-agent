# tests/test_chat_assistant.py : assistant conversationnel sur les résultats d'une analyse
import json

import pandas as pd
import pytest

import agent.tools.chat_assistant as chat_assistant
from agent.llm.config import LLMUnavailableError
from agent.tools.data_loader import load_data


def _schema_for(csv_path):
    return load_data(csv_path)["schema"]


@pytest.fixture
def sample_csv_and_db(tmp_path):
    df = pd.DataFrame({"platform": ["mobile", "web", "mobile", "desktop"], "amount": [10, 20, 30, 40]})
    csv_path = tmp_path / "ventes.csv"
    df.to_csv(csv_path, index=False)
    db_path = str(tmp_path / "analytics.duckdb")
    meta = load_data(str(csv_path), db_path=db_path)
    return meta["table_name"], meta["schema"], db_path


def test_answer_question_without_query_returns_direct_answer(monkeypatch, sample_csv_and_db):
    table_name, schema, db_path = sample_csv_and_db
    monkeypatch.setattr(
        chat_assistant, "get_llm_response",
        lambda **kwargs: json.dumps({"needs_query": False, "answer": "La réponse est déjà dans le résumé."}),
    )
    result = chat_assistant.answer_question(
        question="Quelle est la métrique définie ?", table_name=table_name, schema=schema,
        analysis_context="Métrique : total des ventes.", history=[], db_path=db_path,
    )
    assert result["answer"] == "La réponse est déjà dans le résumé."
    assert result["sql"] is None


def test_answer_question_executes_a_real_read_query(monkeypatch, sample_csv_and_db):
    table_name, schema, db_path = sample_csv_and_db
    calls = []

    def fake_llm(messages, **kwargs):
        prompt = messages[0]["content"]
        calls.append(prompt)
        if len(calls) == 1:
            sql = f'SELECT platform, COUNT(*) as n FROM "{table_name}" GROUP BY platform'
            return json.dumps({"needs_query": True, "sql": sql})
        return "La plateforme mobile est la plus fréquente, avec 2 lignes."

    monkeypatch.setattr(chat_assistant, "get_llm_response", fake_llm)

    result = chat_assistant.answer_question(
        question="Quelle plateforme revient le plus souvent ?", table_name=table_name, schema=schema,
        analysis_context="", history=[], db_path=db_path,
    )

    assert result["sql"] is not None
    assert "mobile" in result["answer"]
    # Le second appel doit avoir reçu le vrai résultat de la requête, pas un
    # texte générique -- preuve que fetch_dataframe() a bien été exécuté.
    assert "mobile" in calls[1] and "platform" in calls[1]


def test_answer_question_rejects_write_query_and_feeds_error_to_followup(monkeypatch, sample_csv_and_db):
    table_name, schema, db_path = sample_csv_and_db
    calls = []

    def fake_llm(messages, **kwargs):
        prompt = messages[0]["content"]
        calls.append(prompt)
        if len(calls) == 1:
            return json.dumps({"needs_query": True, "sql": f'DROP TABLE "{table_name}"'})
        return "Je ne peux pas répondre à cette question pour le moment."

    monkeypatch.setattr(chat_assistant, "get_llm_response", fake_llm)

    result = chat_assistant.answer_question(
        question="Supprime tout", table_name=table_name, schema=schema,
        analysis_context="", history=[], db_path=db_path,
    )

    # La requête d'écriture n'a jamais dû s'exécuter -- la table existe encore.
    assert load_data.__module__  # sanity import check
    from agent.tools.data_loader import fetch_dataframe
    still_there = fetch_dataframe(f'SELECT COUNT(*) FROM "{table_name}"', db_path=db_path)
    assert still_there.iloc[0, 0] == 4
    # Le détail de l'erreur (pas la question originale) part dans le second prompt.
    assert "écriture" in calls[1] or "refus" in calls[1].lower() or "Erreur" in calls[1]
    assert result["sql"].strip().startswith("DROP")


def test_answer_question_falls_back_to_raw_text_on_bad_json(monkeypatch, sample_csv_and_db):
    table_name, schema, db_path = sample_csv_and_db
    monkeypatch.setattr(chat_assistant, "get_llm_response", lambda **kwargs: "Je ne réponds pas en JSON, désolé.")

    result = chat_assistant.answer_question(
        question="Une question", table_name=table_name, schema=schema,
        analysis_context="", history=[], db_path=db_path,
    )

    assert result["answer"] == "Je ne réponds pas en JSON, désolé."
    assert result["sql"] is None


def test_answer_question_propagates_llm_unavailable_error(monkeypatch, sample_csv_and_db):
    table_name, schema, db_path = sample_csv_and_db

    def raise_unavailable(**kwargs):
        raise LLMUnavailableError("Le service d'analyse IA n'est pas configuré pour le moment.")

    monkeypatch.setattr(chat_assistant, "get_llm_response", raise_unavailable)

    with pytest.raises(LLMUnavailableError):
        chat_assistant.answer_question(
            question="Une question", table_name=table_name, schema=schema,
            analysis_context="", history=[], db_path=db_path,
        )


def test_answer_question_caps_history_sent_to_prompt(sample_csv_and_db):
    table_name, schema, db_path = sample_csv_and_db
    long_history = [{"role": "user", "content": f"question {i}"} for i in range(20)]
    prompt = chat_assistant._build_prompt("nouvelle question", table_name, schema, "contexte", long_history)
    assert "question 19" in prompt  # le tour le plus récent est gardé
    assert "question 0" not in prompt  # les plus anciens sont tronqués
