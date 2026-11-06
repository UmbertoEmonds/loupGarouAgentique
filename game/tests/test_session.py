import time

from django.test import SimpleTestCase, override_settings

from engine.models import Phase
from game.session import session


def wait_until(predicate, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@override_settings(FAKE_AI=True, FAKE_AI_DELAY_S=0, PHASE_PAUSE_S=0, HUMAN_TIMEOUT_S=0.05, DEBATE_DURATION_S=5)
class SessionTests(SimpleTestCase):
    def setUp(self):
        session.abandon()
        session.reset()

    def tearDown(self):
        session.abandon()

    def test_full_game_runs_to_a_winner_even_if_human_never_answers(self):
        self.assertTrue(session.start("owner", "Alice"))
        self.assertTrue(wait_until(lambda: session.finished and not session.running))
        snap = session.snapshot()
        self.assertEqual(snap["phase"], Phase.TERMINEE.value)
        self.assertIn(snap["winner"], ("loups", "villageois"))
        # Fin de partie : tous les rôles sont révélés.
        self.assertTrue(all(p["role"] for p in snap["players"]))

    def test_snapshot_hides_other_roles_and_wolf_room(self):
        session.start("owner", "Alice")
        snap = session.snapshot()
        others = [p for p in snap["players"] if not p["is_me"] and p["alive"]]
        if snap["me"]["role"] == "loup":
            # Un loup connaît déjà ses alliés : seuls les autres loups sont révélés.
            self.assertTrue(all((p["role"] == "loup") == (p["pseudo"] in snap["wolf_mates"]) for p in others))
        else:
            self.assertTrue(all(p["role"] is None for p in others))
            self.assertIsNone(snap["wolf_log"])

    def test_second_start_refused_while_running_then_allowed_after_abandon(self):
        self.assertTrue(session.start("owner", "Alice"))
        self.assertFalse(session.start("other", "Bob"))
        session.abandon()
        self.assertTrue(session.start("other", "Bob"))
        self.assertTrue(session.is_owner("other"))
        self.assertFalse(session.is_owner("owner"))


@override_settings(FAKE_AI=True, FAKE_AI_DELAY_S=0.2, PHASE_PAUSE_S=0, HUMAN_TIMEOUT_S=5, DEBATE_DURATION_S=60,
                   IDLE_ABANDON_S=0.1)
class IdleAbandonTests(SimpleTestCase):
    def setUp(self):
        session.abandon()
        session.reset()
        session.clients = 0

    def tearDown(self):
        session.abandon()
        session.clients = 0

    def test_game_abandoned_when_last_client_leaves(self):
        session.start("owner", "Alice")
        session.client_connected()
        session.client_disconnected()
        self.assertTrue(wait_until(lambda: not session.running, timeout=5))

    def test_reconnecting_within_grace_period_keeps_the_game(self):
        session.start("owner", "Alice")
        session.client_connected()
        session.client_disconnected()
        session.client_connected()
        time.sleep(0.4)
        self.assertTrue(session.running)

    def test_game_kept_while_another_client_is_connected(self):
        session.start("owner", "Alice")
        session.client_connected()
        session.client_connected()
        session.client_disconnected()
        time.sleep(0.4)
        self.assertTrue(session.running)


@override_settings(FAKE_AI=True, FAKE_AI_DELAY_S=0.2, PHASE_PAUSE_S=0, HUMAN_TIMEOUT_S=5, DEBATE_DURATION_S=60)
class AbandonTests(SimpleTestCase):
    def setUp(self):
        session.abandon()
        session.reset()

    def tearDown(self):
        session.abandon()

    def test_abandon_stops_the_game_immediately(self):
        session.start("owner", "Alice")
        self.assertTrue(session.running)
        session.abandon()
        self.assertFalse(session.running)
        self.assertIsNone(session.thinking)


@override_settings(FAKE_AI=True, FAKE_AI_DELAY_S=0, PHASE_PAUSE_S=0, HUMAN_TIMEOUT_S=0.05, DEBATE_DURATION_S=5)
class AIStatsTests(SimpleTestCase):
    def setUp(self):
        session.abandon()
        session.reset()

    def tearDown(self):
        session.abandon()

    def test_stats_start_empty_in_the_snapshot(self):
        session.start("owner", "Alice")
        stats = session.snapshot()["ai_stats"]
        self.assertEqual(stats["total_tokens"], 0)
        self.assertEqual(stats["calls"], 0)

    def test_each_call_updates_the_model_and_cumulates_tokens(self):
        session.start("owner", "Alice")
        gen = session._gen
        session._record_ai_call(gen, "vendor/model-a", {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10})
        session._record_ai_call(gen, "vendor/model-b", {"prompt_tokens": 4, "completion_tokens": 1})
        stats = session._public_ai_stats(Phase.JOUR_DEBAT)
        self.assertEqual(stats, {"model": "vendor/model-b", "calls": 2, "total_tokens": 15})

    def test_calls_from_an_older_game_are_ignored(self):
        session.start("owner", "Alice")
        old_gen = session._gen
        session.start("owner", "Alice")
        session._record_ai_call(old_gen, "old", {"total_tokens": 99})
        self.assertEqual(session.snapshot()["ai_stats"]["total_tokens"], 0)

    def test_stats_are_frozen_at_night_so_they_reveal_nothing(self):
        session.start("owner", "Alice")
        gen = session._gen
        session._record_ai_call(gen, "jour", {"total_tokens": 10})
        self.assertEqual(session._public_ai_stats(Phase.JOUR_DEBAT)["total_tokens"], 10)
        session._record_ai_call(gen, "nuit", {"total_tokens": 5})
        self.assertEqual(session._public_ai_stats(Phase.NUIT_SORCIERE),
                         {"model": "jour", "calls": 1, "total_tokens": 10})
        self.assertEqual(session._public_ai_stats(Phase.JOUR_DEBAT)["total_tokens"], 15)
