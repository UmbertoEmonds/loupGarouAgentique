import pytest
import requests

from agents.client import FallbackClient, GroqClient, GroqError, OpenRouterClient, OpenRouterError


class FakeResponse:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
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


# ---- GroqClient : la logique HTTP/retry est déjà couverte ci-dessus via la
# base partagée _ChatCompletionClient, on vérifie juste ce qui lui est propre.

def test_groq_client_posts_to_the_groq_endpoint_with_bearer_auth():
    session = FakeSession([ok_response("salut")])
    client = GroqClient(models=["m/groq"], api_key="k", session=session)
    client.complete("sys", "user")
    assert session.requests[0]["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert session.requests[0]["headers"]["Authorization"] == "Bearer k"

def test_groq_client_defaults_to_models_still_served_by_groq(monkeypatch):
    # llama-3.1-8b-instant a été retiré par Groq (404 constaté le 2026-11-06).
    monkeypatch.delenv("GROQ_MODELS", raising=False)
    client = GroqClient(api_key="k", session=FakeSession([]))
    assert client.models == ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]

def test_groq_client_reads_models_from_environment(monkeypatch):
    monkeypatch.setenv("GROQ_MODELS", "env/groq,env2/groq")
    client = GroqClient(api_key="k", session=FakeSession([]))
    assert client.models == ["env/groq", "env2/groq"]

def test_groq_client_raises_groqerror_when_every_model_fails():
    session = FakeSession([FakeResponse(500, {})])
    client = GroqClient(models=["m/groq"], api_key="k", session=session)
    with pytest.raises(GroqError):
        client.complete("sys", "user")


# ---- FallbackClient --------------------------------------------------------

def test_fallback_client_returns_the_first_clients_result_on_success():
    primary = GroqClient(models=["m/groq"], api_key="k", session=FakeSession([ok_response("ok")]))
    client = FallbackClient([primary])
    assert client.complete("sys", "user") == "ok"

def test_fallback_client_tries_the_next_client_after_the_first_is_exhausted():
    primary = OpenRouterClient(models=["m/free"], api_key="k", session=FakeSession([FakeResponse(500, {})]))
    secondary = GroqClient(models=["m/groq"], api_key="k", session=FakeSession([ok_response("secours")]))
    client = FallbackClient([primary, secondary])
    assert client.complete("sys", "user") == "secours"

def test_fallback_client_raises_the_last_clients_error_when_all_fail():
    primary = OpenRouterClient(models=["m/free"], api_key="k", session=FakeSession([FakeResponse(500, {})]))
    secondary = GroqClient(models=["m/groq"], api_key="k", session=FakeSession([FakeResponse(500, {})]))
    client = FallbackClient([primary, secondary])
    with pytest.raises(GroqError):
        client.complete("sys", "user")

def test_fallback_client_requires_at_least_one_client():
    with pytest.raises(ValueError):
        FallbackClient([])

def test_complete_passes_the_usage_of_a_successful_call_to_on_usage():
    usage = {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
    payload = {"choices": [{"message": {"content": "ok"}}], "usage": usage}
    seen = []
    session = FakeSession([FakeResponse(200, payload)])
    client = OpenRouterClient(models=["m"], api_key="k", session=session, on_usage=seen.append)
    assert client.complete("sys", "user") == "ok"
    assert seen == [usage]

def test_on_usage_is_only_called_for_the_successful_attempt():
    seen = []
    session = FakeSession([FakeResponse(500, {"usage": {"total_tokens": 1}}), ok_response("ok")])
    client = OpenRouterClient(models=["a", "b"], api_key="k", session=session, on_usage=seen.append)
    client.complete("sys", "user")
    assert seen == [None]  # ok_response ne contient pas d'usage

def test_a_failing_on_usage_callback_never_breaks_the_call():
    def boom(_usage):
        raise RuntimeError
    session = FakeSession([ok_response("ok")])
    client = OpenRouterClient(models=["m"], api_key="k", session=session, on_usage=boom)
    assert client.complete("sys", "user") == "ok"

def test_complete_reports_the_model_and_usage_to_on_call():
    usage = {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
    payload = {"model": "vendor/real-model", "choices": [{"message": {"content": "ok"}}], "usage": usage}
    seen = []
    session = FakeSession([FakeResponse(200, payload)])
    client = OpenRouterClient(models=["requested"], api_key="k", session=session,
                              on_call=lambda model, u: seen.append((model, u)))
    client.complete("sys", "user")
    assert seen == [("vendor/real-model", usage)]

def test_on_call_falls_back_to_the_requested_model_name():
    seen = []
    session = FakeSession([ok_response("ok")])
    client = OpenRouterClient(models=["requested"], api_key="k", session=session,
                              on_call=lambda model, u: seen.append(model))
    client.complete("sys", "user")
    assert seen == ["requested"]

def test_a_failing_on_call_callback_never_breaks_the_call():
    def boom(model, usage):
        raise RuntimeError
    session = FakeSession([ok_response("ok")])
    client = OpenRouterClient(models=["m"], api_key="k", session=session, on_call=boom)
    assert client.complete("sys", "user") == "ok"


# ---- Quota par minute (429 + retry-after) ----------------------------------
# Groq limite chaque modèle à 8000 jetons par minute. Sans attente, le client
# abandonnait au premier refus et le débat s'effondrait en deux secondes
# (chaque échec compte comme « je passe »).

def rate_limited(seconds):
    return FakeResponse(429, {}, headers={"retry-after": str(seconds)})

def test_rate_limited_models_are_retried_after_the_shortest_wait():
    session = FakeSession([rate_limited(6), rate_limited(3), ok_response("après attente")])
    waits = []
    client = GroqClient(models=["a", "b"], api_key="k", session=session, sleep=waits.append)
    assert client.complete("sys", "user") == "après attente"
    assert waits == [3.0]
    assert [r["json"]["model"] for r in session.requests] == ["a", "b", "a"]

def test_another_model_with_capacity_is_used_before_waiting():
    session = FakeSession([rate_limited(5), ok_response("b répond")])
    waits = []
    client = GroqClient(models=["a", "b"], api_key="k", session=session, sleep=waits.append)
    assert client.complete("sys", "user") == "b répond"
    assert waits == []

def test_a_daily_quota_is_not_waited_for():
    # retry-after de plusieurs minutes : quota du jour épuisé, inutile d'attendre.
    session = FakeSession([rate_limited(420)])
    waits = []
    client = GroqClient(models=["a"], api_key="k", session=session, sleep=waits.append)
    with pytest.raises(GroqError):
        client.complete("sys", "user")
    assert waits == []

def test_a_per_minute_quota_is_waited_for_even_beyond_ten_seconds():
    session = FakeSession([rate_limited(35), ok_response("ok")])
    waits = []
    client = GroqClient(models=["a"], api_key="k", session=session, sleep=waits.append)
    assert client.complete("sys", "user") == "ok"
    assert waits == [35.0]

def test_the_client_waits_only_once_per_call():
    session = FakeSession([rate_limited(2), rate_limited(2)])
    waits = []
    client = GroqClient(models=["a"], api_key="k", session=session, sleep=waits.append)
    with pytest.raises(GroqError):
        client.complete("sys", "user")
    assert waits == [2.0]
