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
    client = OpenRouterClient(models=["m/free"], api_key="k", session=session)
    assert client.complete("sys", "user") == "salut"
    assert session.requests[0]["json"]["model"] == "m/free"
    assert session.requests[0]["timeout"] == 15.0

def test_complete_tries_the_next_model_after_the_first_fails():
    session = FakeSession([FakeResponse(500, {}), ok_response("secours")])
    client = OpenRouterClient(models=["m/free", "m2/free"], api_key="k", session=session)
    assert client.complete("sys", "user") == "secours"
    assert session.requests[1]["json"]["model"] == "m2/free"

def test_complete_tries_every_model_in_order_until_one_succeeds():
    session = FakeSession([FakeResponse(500, {}), FakeResponse(500, {}), ok_response("troisieme")])
    client = OpenRouterClient(models=["m/free", "m2/free", "m3/free"], api_key="k", session=session)
    assert client.complete("sys", "user") == "troisieme"
    assert session.requests[0]["json"]["model"] == "m/free"
    assert session.requests[1]["json"]["model"] == "m2/free"
    assert session.requests[2]["json"]["model"] == "m3/free"

def test_complete_raises_when_every_model_fails():
    session = FakeSession([FakeResponse(500, {}), FakeResponse(500, {})])
    client = OpenRouterClient(models=["m/free", "m2/free"], api_key="k", session=session)
    with pytest.raises(OpenRouterError):
        client.complete("sys", "user")

def test_complete_raises_with_a_single_model_configured():
    session = FakeSession([FakeResponse(500, {})])
    client = OpenRouterClient(models=["m/free"], api_key="k", session=session)
    with pytest.raises(OpenRouterError):
        client.complete("sys", "user")

def test_complete_raises_immediately_with_no_models_configured():
    session = FakeSession([])
    client = OpenRouterClient(models=[], api_key="k", session=session)
    with pytest.raises(OpenRouterError):
        client.complete("sys", "user")
    assert session.requests == []

def test_constructor_reads_models_from_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODELS", "env/free,env2/free")
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    client = OpenRouterClient(session=FakeSession([]))
    assert client.models == ["env/free", "env2/free"]

def test_models_env_var_is_split_on_commas_and_whitespace_trimmed(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODELS", " m/free , m2/free ,, ")
    client = OpenRouterClient(api_key="k", session=FakeSession([]))
    assert client.models == ["m/free", "m2/free"]

def test_no_models_env_var_produces_an_empty_list(monkeypatch):
    monkeypatch.delenv("OPENROUTER_MODELS", raising=False)
    client = OpenRouterClient(api_key="k", session=FakeSession([]))
    assert client.models == []

def test_complete_raises_openroutererror_on_malformed_200_response():
    session = FakeSession([FakeResponse(200, {"choices": []})])
    client = OpenRouterClient(models=["m/free"], api_key="k", session=session)
    with pytest.raises(OpenRouterError):
        client.complete("sys", "user")

def test_complete_tries_the_next_model_after_a_malformed_200_response():
    session = FakeSession([FakeResponse(200, {"id": "x"}), ok_response("secours")])
    client = OpenRouterClient(models=["m/free", "m2/free"], api_key="k", session=session)
    assert client.complete("sys", "user") == "secours"
    assert session.requests[1]["json"]["model"] == "m2/free"

def test_complete_treats_a_network_timeout_as_a_failed_attempt_and_tries_the_next_model():
    session = FakeSession([requests.exceptions.Timeout("timed out"), ok_response("secours")])
    client = OpenRouterClient(models=["m/free", "m2/free"], api_key="k", session=session)
    assert client.complete("sys", "user") == "secours"
    assert session.requests[1]["json"]["model"] == "m2/free"

def test_complete_raises_openroutererror_on_network_timeout_with_a_single_model():
    session = FakeSession([requests.exceptions.Timeout("timed out")])
    client = OpenRouterClient(models=["m/free"], api_key="k", session=session)
    with pytest.raises(OpenRouterError):
        client.complete("sys", "user")
