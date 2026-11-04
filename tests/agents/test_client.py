import pytest
import requests

from agents.client import OpenRouterClient, OpenRouterError


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
    def json(self):
        return self._payload

class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
    def post(self, url, json, headers, timeout):
        self.requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

def ok_response(text):
    return FakeResponse(200, {"choices": [{"message": {"content": text}}]})

def test_complete_returns_assistant_text_on_success():
    session = FakeSession([ok_response("salut")])
    client = OpenRouterClient(model="m/free", api_key="k", session=session)
    assert client.complete("sys", "user") == "salut"
    assert session.requests[0]["json"]["model"] == "m/free"
    assert session.requests[0]["timeout"] == 15.0

def test_complete_uses_fallback_model_after_primary_fails():
    session = FakeSession([FakeResponse(500, {}), ok_response("secours")])
    client = OpenRouterClient(model="m/free", fallback_model="m2/free", api_key="k", session=session)
    assert client.complete("sys", "user") == "secours"
    assert session.requests[1]["json"]["model"] == "m2/free"

def test_complete_raises_when_both_models_fail():
    session = FakeSession([FakeResponse(500, {}), FakeResponse(500, {})])
    client = OpenRouterClient(model="m/free", fallback_model="m2/free", api_key="k", session=session)
    with pytest.raises(OpenRouterError):
        client.complete("sys", "user")

def test_complete_raises_with_no_fallback_configured():
    session = FakeSession([FakeResponse(500, {})])
    client = OpenRouterClient(model="m/free", api_key="k", session=session)
    with pytest.raises(OpenRouterError):
        client.complete("sys", "user")

def test_constructor_reads_model_from_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "env/free")
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    client = OpenRouterClient(session=FakeSession([]))
    assert client.model == "env/free"

def test_complete_raises_openroutererror_on_malformed_200_response():
    session = FakeSession([FakeResponse(200, {"choices": []})])
    client = OpenRouterClient(model="m/free", api_key="k", session=session)
    with pytest.raises(OpenRouterError):
        client.complete("sys", "user")

def test_complete_uses_fallback_model_after_malformed_200_response():
    session = FakeSession([FakeResponse(200, {"id": "x"}), ok_response("secours")])
    client = OpenRouterClient(model="m/free", fallback_model="m2/free", api_key="k", session=session)
    assert client.complete("sys", "user") == "secours"
    assert session.requests[1]["json"]["model"] == "m2/free"

def test_complete_treats_a_network_timeout_as_a_failed_attempt_and_uses_fallback():
    session = FakeSession([requests.exceptions.Timeout("timed out"), ok_response("secours")])
    client = OpenRouterClient(model="m/free", fallback_model="m2/free", api_key="k", session=session)
    assert client.complete("sys", "user") == "secours"
    assert session.requests[1]["json"]["model"] == "m2/free"

def test_complete_raises_openroutererror_on_network_timeout_with_no_fallback():
    session = FakeSession([requests.exceptions.Timeout("timed out")])
    client = OpenRouterClient(model="m/free", api_key="k", session=session)
    with pytest.raises(OpenRouterError):
        client.complete("sys", "user")

def test_fallback_model_string_is_split_on_commas_and_whitespace_trimmed():
    client = OpenRouterClient(
        model="m/free", fallback_model=" m2/free , m3/free ,, ", api_key="k", session=FakeSession([])
    )
    assert client.fallback_models == ["m2/free", "m3/free"]

def test_single_fallback_model_produces_a_one_item_list():
    client = OpenRouterClient(model="m/free", fallback_model="m2/free", api_key="k", session=FakeSession([]))
    assert client.fallback_models == ["m2/free"]

def test_no_fallback_model_produces_an_empty_list():
    client = OpenRouterClient(model="m/free", api_key="k", session=FakeSession([]))
    assert client.fallback_models == []

def test_complete_tries_multiple_fallback_models_in_order_until_one_succeeds():
    session = FakeSession([FakeResponse(500, {}), FakeResponse(500, {}), ok_response("troisieme")])
    client = OpenRouterClient(model="m/free", fallback_model="m2/free,m3/free", api_key="k", session=session)
    assert client.complete("sys", "user") == "troisieme"
    assert session.requests[0]["json"]["model"] == "m/free"
    assert session.requests[1]["json"]["model"] == "m2/free"
    assert session.requests[2]["json"]["model"] == "m3/free"

def test_complete_raises_when_all_fallback_models_fail():
    session = FakeSession([FakeResponse(500, {}), FakeResponse(500, {}), FakeResponse(500, {})])
    client = OpenRouterClient(model="m/free", fallback_model="m2/free,m3/free", api_key="k", session=session)
    with pytest.raises(OpenRouterError):
        client.complete("sys", "user")

def test_constructor_reads_comma_separated_fallback_models_from_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "env/free")
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODEL", "env2/free,env3/free")
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    client = OpenRouterClient(session=FakeSession([]))
    assert client.fallback_models == ["env2/free", "env3/free"]
