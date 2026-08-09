# tests/test_llm_config.py — Extraction de JSON et repli entre providers LLM
import json

import pytest

import agent.llm.config as llm_config
from agent.llm.config import LLMUnavailableError, extract_json, get_llm_response


def test_extract_json_from_raw_json():
    text = '{"metric": "retention", "value": 42}'
    assert extract_json(text) == {"metric": "retention", "value": 42}


def test_extract_json_from_fenced_code_block():
    text = '```json\n{"metric": "retention", "value": 42}\n```'
    assert extract_json(text) == {"metric": "retention", "value": 42}


def test_extract_json_from_fenced_block_without_language_tag():
    text = '```\n{"a": 1}\n```'
    assert extract_json(text) == {"a": 1}


def test_extract_json_with_leading_prose():
    text = 'Voici mon analyse :\n\n{"a": 1, "b": 2}'
    assert extract_json(text) == {"a": 1, "b": 2}


def test_extract_json_with_trailing_prose():
    text = '{"a": 1, "b": 2}\n\nJ\'espère que cela vous aide !'
    assert extract_json(text) == {"a": 1, "b": 2}


def test_extract_json_raises_on_no_json():
    with pytest.raises(json.JSONDecodeError):
        extract_json("Je ne peux pas répondre à cette question.")


# --- get_llm_response() : repli entre providers ---

class _FakeChoice:
    def __init__(self, content):
        self.message = type("Msg", (), {"content": content})()


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


def _clear_all_provider_keys(monkeypatch):
    for key in ["GROQ_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "MISTRAL_API_KEY"]:
        monkeypatch.delenv(key, raising=False)


def test_get_llm_response_raises_when_no_provider_configured(monkeypatch):
    _clear_all_provider_keys(monkeypatch)
    with pytest.raises(LLMUnavailableError, match="Aucun provider"):
        get_llm_response([{"role": "user", "content": "salut"}], provider="groq")


def test_get_llm_response_falls_back_to_next_configured_provider(monkeypatch):
    _clear_all_provider_keys(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key")
    monkeypatch.setenv("MISTRAL_API_KEY", "fake-mistral-key")

    def fake_completion(model, messages, api_key, temperature, max_tokens):
        if model.startswith("groq/"):
            raise RuntimeError("quota Groq épuisé")
        if model.startswith("mistral/"):
            return _FakeResponse("réponse de secours via Mistral")
        raise AssertionError(f"modèle inattendu : {model}")

    monkeypatch.setattr(llm_config, "completion", fake_completion)

    result = get_llm_response([{"role": "user", "content": "salut"}], provider="groq")
    assert result == "réponse de secours via Mistral"


def test_get_llm_response_skips_providers_without_api_key(monkeypatch):
    _clear_all_provider_keys(monkeypatch)
    monkeypatch.setenv("MISTRAL_API_KEY", "fake-mistral-key")

    calls = []

    def fake_completion(model, messages, api_key, temperature, max_tokens):
        calls.append(model)
        return _FakeResponse("ok")

    monkeypatch.setattr(llm_config, "completion", fake_completion)

    result = get_llm_response([{"role": "user", "content": "salut"}], provider="groq")
    assert result == "ok"
    # Ni groq (pas de clé) ni openrouter (pas de clé) n'ont dû être appelés.
    assert calls == ["mistral/mistral-large-latest"]


def test_get_llm_response_raises_with_detail_when_all_providers_fail(monkeypatch):
    _clear_all_provider_keys(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-openrouter-key")

    def fake_completion(model, messages, api_key, temperature, max_tokens):
        raise RuntimeError(f"échec pour {model}")

    monkeypatch.setattr(llm_config, "completion", fake_completion)

    with pytest.raises(LLMUnavailableError, match="indisponibles"):
        get_llm_response([{"role": "user", "content": "salut"}], provider="groq")


def test_openrouter_fallback_tries_next_free_model_before_giving_up(monkeypatch):
    _clear_all_provider_keys(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")

    def fake_completion(model, messages, api_key, temperature, max_tokens):
        if model == llm_config.OPENROUTER_FALLBACK_MODELS[0]:
            raise RuntimeError("rate limit sur ce modèle précis")
        if model == llm_config.OPENROUTER_FALLBACK_MODELS[1]:
            return _FakeResponse("deuxième modèle gratuit OK")
        raise AssertionError(f"ne devrait pas essayer {model}")

    monkeypatch.setattr(llm_config, "completion", fake_completion)

    result = get_llm_response([{"role": "user", "content": "salut"}], provider="openrouter")
    assert result == "deuxième modèle gratuit OK"


def test_get_llm_response_with_explicit_model_makes_a_single_attempt(monkeypatch):
    _clear_all_provider_keys(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key")

    calls = []

    def fake_completion(model, messages, api_key, temperature, max_tokens):
        calls.append(model)
        return _FakeResponse("réponse du modèle explicite")

    monkeypatch.setattr(llm_config, "completion", fake_completion)

    result = get_llm_response(
        [{"role": "user", "content": "salut"}], provider="groq", model="groq/un-modele-precis",
    )
    assert result == "réponse du modèle explicite"
    assert calls == ["groq/un-modele-precis"]
