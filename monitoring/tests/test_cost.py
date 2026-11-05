from django.test import TestCase

from agents.client import OpenRouterClient
from monitoring.cost import RoundCostTracker
from monitoring.models import Game, RoundCost


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


class RoundCostTrackerTests(TestCase):
    def test_tokens_are_summed_per_round_in_the_database(self):
        current = {"round": 1}
        tracker = RoundCostTracker(lambda: current["round"], game_id="g1")

        tracker.record({"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120})
        tracker.record({"prompt_tokens": 50, "completion_tokens": 5})  # total absent -> calculé
        current["round"] = 2
        tracker.record({"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11})
        tracker.record(None)  # pas d'usage renvoyé : ignoré

        report = tracker.report()
        self.assertEqual(report["rounds"], [
            {"round": 1, "calls": 2, "prompt_tokens": 150, "completion_tokens": 25, "total_tokens": 175},
            {"round": 2, "calls": 1, "prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
        ])
        self.assertEqual(report["total"],
                         {"calls": 3, "prompt_tokens": 160, "completion_tokens": 26, "total_tokens": 186})
        self.assertEqual(Game.objects.get().game_id, "g1")

    def test_no_game_row_without_any_usage(self):
        RoundCostTracker(lambda: 1, game_id="vide").record(None)
        self.assertFalse(Game.objects.exists())

    def test_each_game_gets_its_own_rows(self):
        RoundCostTracker(lambda: 1, game_id="a").record({"total_tokens": 5})
        RoundCostTracker(lambda: 1, game_id="b").record({"total_tokens": 7})
        self.assertEqual(Game.objects.count(), 2)
        self.assertEqual(RoundCost.objects.get(game__game_id="b").total_tokens, 7)

    def test_client_reports_usage_into_the_tracker(self):
        tracker = RoundCostTracker(lambda: 1, game_id="g2")
        usage = {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
        session = FakeSession([{"choices": [{"message": {"content": "ok"}}], "usage": usage}])
        client = OpenRouterClient(models=["m"], api_key="k", session=session, on_usage=tracker.record)

        self.assertEqual(client.complete("s", "u"), "ok")
        self.assertEqual(tracker.report()["total"]["total_tokens"], 10)
