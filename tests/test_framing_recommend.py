# tests/test_framing_recommend.py — framing_node/recommend_node de bout en bout
#
# framing_node et recommend_node appellent un LLM ; jusqu'ici ils n'étaient
# couverts par aucun test automatisé (voir README) car les vérifier
# semblait nécessiter soit un vrai appel LLM (coûteux, non déterministe),
# soit un mock de get_llm_response() qui ne testerait que l'appel, pas le
# traitement de sa réponse (extraction JSON, repli en cas d'échec...).
#
# Entre les deux : ne simuler QUE le réseau (litellm.completion), avec des
# réponses représentatives de ce qu'un vrai modèle renvoie (JSON dans un
# bloc ```json, ou texte libre sans JSON du tout) -- get_llm_response(),
# extract_json() et la logique des nœuds tournent alors pour de vrai, sans
# dépendre d'un provider externe ni de sa disponibilité du jour.
import agent.llm.config as llm_config
from agent.nodes.framing import framing_node
from agent.nodes.recommend import recommend_node
from agent.state import AgentState, AnalysisStatus


class _FakeChoice:
    def __init__(self, content):
        self.message = type("Msg", (), {"content": content})()


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


def _fake_completion(content):
    def fake(model, messages, api_key, temperature, max_tokens):
        return _FakeResponse(content)
    return fake


def _set_only_groq_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    for key in ["GOOGLE_API_KEY", "OPENROUTER_API_KEY", "MISTRAL_API_KEY"]:
        monkeypatch.delenv(key, raising=False)


def test_framing_node_parses_realistic_fenced_json_response(monkeypatch):
    _set_only_groq_key(monkeypatch)
    realistic_response = """Voici le cadrage demandé :

```json
{
    "metric_definition": "Taux de rétention à 7 jours",
    "business_question": "Pourquoi la rétention mobile a-t-elle baissé ?",
    "comparison_period": "4 dernières semaines vs 4 précédentes",
    "assumptions": ["Les données couvrent une période représentative"]
}
```
"""
    monkeypatch.setattr(llm_config, "completion", _fake_completion(realistic_response))

    state = AgentState(query="Pourquoi la rétention baisse ?", data_path="data.csv", llm_provider="groq")
    result = framing_node(state)

    assert result["status"] == AnalysisStatus.INSPECTION
    assert result["metric_definition"] == "Taux de rétention à 7 jours"
    assert result["business_question"] == "Pourquoi la rétention mobile a-t-elle baissé ?"
    assert result["comparison_period"] == "4 dernières semaines vs 4 précédentes"
    assert result["assumptions"] == ["Les données couvrent une période représentative"]
    assert "Pourquoi la rétention mobile" in result["audit_trail"][-1]


def test_framing_node_mentions_joined_files_and_parses_response(monkeypatch):
    _set_only_groq_key(monkeypatch)
    captured = {}

    def fake_completion(model, messages, api_key, temperature, max_tokens):
        captured["prompt"] = messages[0]["content"]
        return _FakeResponse('{"metric_definition": "m", "business_question": "q", '
                              '"comparison_period": "p", "assumptions": []}')

    monkeypatch.setattr(llm_config, "completion", fake_completion)

    join_spec = {"root": "commandes.csv", "joins": [
        {"file": "clients.csv", "on_file": "commandes.csv",
         "file_column": "id", "on_column": "client_id", "how": "inner"},
    ]}
    state = AgentState(
        query="q", data_path="commandes.csv", data_paths=["commandes.csv", "clients.csv"],
        join_spec=join_spec, llm_provider="groq",
    )
    result = framing_node(state)

    assert "commandes.csv" in captured["prompt"]
    assert "clients.csv" in captured["prompt"]
    assert result["business_question"] == "q"


def test_framing_node_falls_back_when_response_has_no_json(monkeypatch):
    _set_only_groq_key(monkeypatch)
    monkeypatch.setattr(
        llm_config, "completion",
        _fake_completion("Je ne suis pas en mesure de répondre à cette question pour le moment."),
    )

    state = AgentState(query="question d'origine", data_path="data.csv", llm_provider="groq")
    result = framing_node(state)

    assert result["status"] == AnalysisStatus.INSPECTION
    assert result["business_question"] == "question d'origine"
    assert result["metric_definition"] == "Non définie (erreur de parsing)"
    assert "non structurée" in result["audit_trail"][-1]


def test_recommend_node_parses_realistic_json_response(monkeypatch):
    _set_only_groq_key(monkeypatch)
    realistic_response = """{
  "recommendations": [
    {
      "title": "Améliorer l'onboarding mobile",
      "description": "La baisse de rétention est concentrée sur la plateforme mobile.",
      "impact": "élevé",
      "feasibility": "moyenne",
      "timeline": "court terme"
    }
  ]
}"""
    monkeypatch.setattr(llm_config, "completion", _fake_completion(realistic_response))

    state = AgentState(
        query="q", data_path="data.csv", llm_provider="groq",
        business_question="q", metric_definition="m",
        statistical_tests={"platform": {"significant": True, "p_value": 0.01}},
    )
    result = recommend_node(state)

    assert result["status"] == AnalysisStatus.EXPORTING
    assert len(result["recommendations"]) == 1
    rec = result["recommendations"][0]
    assert rec["title"] == "Améliorer l'onboarding mobile"
    assert rec["impact"] == "élevé"
    assert "1 recommandations" in result["audit_trail"][-1]


def test_recommend_node_prioritizes_significant_dimensions_in_prompt(monkeypatch):
    _set_only_groq_key(monkeypatch)
    captured = {}

    def fake_completion(model, messages, api_key, temperature, max_tokens):
        captured["prompt"] = messages[0]["content"]
        return _FakeResponse('{"recommendations": []}')

    monkeypatch.setattr(llm_config, "completion", fake_completion)

    state = AgentState(
        query="q", data_path="data.csv", llm_provider="groq",
        statistical_tests={
            "platform": {"significant": True, "p_value": 0.01},
            "region": {"significant": False, "p_value": 0.8},
        },
    )
    recommend_node(state)

    assert "platform" in captured["prompt"]
    assert "Dimensions statistiquement significatives" in captured["prompt"]


def test_recommend_node_falls_back_to_raw_text_when_unparseable(monkeypatch):
    _set_only_groq_key(monkeypatch)
    monkeypatch.setattr(
        llm_config, "completion", _fake_completion("Réponse en texte libre, sans JSON.")
    )

    state = AgentState(query="q", data_path="data.csv", llm_provider="groq")
    result = recommend_node(state)

    assert result["status"] == AnalysisStatus.EXPORTING
    assert len(result["recommendations"]) == 1
    assert result["recommendations"][0]["description"] == "Réponse en texte libre, sans JSON."
