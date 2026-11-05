import json

from agents.client import OpenRouterClient
from monitoring.cost import RoundCostTracker


class FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)

    def post(self, url, json, headers, timeout):
        return FakeResponse(self.payloads.pop(0))


def test_tokens_are_summed_per_round_and_written_to_one_json_per_game(tmp_path):
    current = {"round": 1}
    tracker = RoundCostTracker(lambda: current["round"], directory=tmp_path, game_id="g1")

    tracker.record({"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120})
    tracker.record({"prompt_tokens": 50, "completion_tokens": 5})  # total absent -> calculé
    current["round"] = 2
    tracker.record({"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11})
    tracker.record(None)  # pas d'usage renvoyé : ignoré

    data = json.loads((tmp_path / "g1.json").read_text(encoding="utf-8"))
    assert data["game_id"] == "g1"
    assert data["rounds"] == [
        {"round": 1, "calls": 2, "prompt_tokens": 150, "completion_tokens": 25, "total_tokens": 175},
        {"round": 2, "calls": 1, "prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
    ]
    assert data["total"] == {"calls": 3, "prompt_tokens": 160, "completion_tokens": 26, "total_tokens": 186}


def test_client_reports_usage_of_successful_calls(tmp_path):
    tracker = RoundCostTracker(lambda: 1, directory=tmp_path, game_id="g2")
    usage = {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
    session = FakeSession([{"choices": [{"message": {"content": "ok"}}], "usage": usage}])
    client = OpenRouterClient(models=["m"], api_key="k", session=session, on_usage=tracker.record)

    assert client.complete("s", "u") == "ok"
    assert tracker.report()["total"]["total_tokens"] == 10


def test_a_failing_usage_callback_never_breaks_the_call():
    def boom(_usage):
        raise RuntimeError

    session = FakeSession([{"choices": [{"message": {"content": "ok"}}], "usage": {}}])
    client = OpenRouterClient(models=["m"], api_key="k", session=session, on_usage=boom)
    assert client.complete("s", "u") == "ok"
