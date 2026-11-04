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
