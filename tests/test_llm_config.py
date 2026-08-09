# tests/test_llm_config.py — Extraction de JSON depuis une réponse LLM imparfaite
import json

import pytest

from agent.llm.config import extract_json


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
