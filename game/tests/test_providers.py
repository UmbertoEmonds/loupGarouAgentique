import random
import threading
import time

from django.test import SimpleTestCase

from agents.client import FallbackClient, GroqClient, OpenRouterClient
from engine.engine import GameEngine
from game.providers import HumanProvider, RouterProvider, build_ai_provider, build_response

VOTE = {"kind": "vote", "allow_message": False, "targets": [{"id": "ia_1", "pseudo": "A"}]}


class BuildResponseTests(SimpleTestCase):
    def test_vote_ok(self):
        resp, err = build_response(VOTE, {"target": "ia_1"})
        self.assertIsNone(err)
        self.assertEqual(resp, {"message": None, "action": {"type": "day_vote", "target": "ia_1"}})

    def test_vote_target_outside_list_is_refused(self):
        resp, err = build_response(VOTE, {"target": "ia_9"})
        self.assertIsNone(resp)
        self.assertTrue(err)

    def test_debate_message_is_cleaned_and_capped(self):
        pending = {"kind": "debate", "allow_message": True, "targets": []}
        resp, _ = build_response(pending, {"message": "  salut   à tous  " + "x" * 900})
        self.assertTrue(resp["message"].startswith("salut à tous"))
        self.assertLessEqual(len(resp["message"]), 500)
        self.assertIsNone(resp["action"])

    def test_debate_empty_message_is_a_pass(self):
        pending = {"kind": "debate", "allow_message": True, "targets": []}
        resp, _ = build_response(pending, {"message": "   "})
        self.assertIsNone(resp["message"])

    def test_message_ignored_when_not_allowed(self):
        resp, _ = build_response(VOTE, {"target": "ia_1", "message": "hello"})
        self.assertIsNone(resp["message"])

    def test_witch_heal_accept_and_decline(self):
        pending = {"kind": "witch_heal", "allow_message": False, "targets": [], "victim_id": "ia_2", "can_accept": True}
        resp, _ = build_response(pending, {"accept": True})
        self.assertEqual(resp["action"], {"type": "witch_heal", "target": "ia_2"})
        resp, _ = build_response(pending, {"accept": False})
        self.assertIsNone(resp["action"])

    def test_witch_cannot_heal_herself(self):
        pending = {"kind": "witch_heal", "allow_message": False, "targets": [], "victim_id": "human", "can_accept": False}
        resp, err = build_response(pending, {"accept": True})
        self.assertIsNone(resp)
        self.assertTrue(err)

    def test_witch_poison_decline_needs_no_target(self):
        pending = {"kind": "witch_poison", "allow_message": False, "targets": [{"id": "ia_1", "pseudo": "A"}]}
        resp, err = build_response(pending, {"accept": False})
        self.assertIsNone(err)
        self.assertIsNone(resp["action"])


class HumanProviderTests(SimpleTestCase):
    def _ask_in_thread(self, human, key, results):
        t = threading.Thread(target=lambda: results.append(human.ask(key, dict(VOTE))))
        t.start()
        return t

    def _wait_pending(self, human):
        for _ in range(200):
            if human.pending:
                return human.pending
            time.sleep(0.01)
        self.fail("no pending request")

    def test_submit_unblocks_ask(self):
        human, results = HumanProvider(timeout_s=5), []
        t = self._ask_in_thread(human, ("k",), results)
        pending = self._wait_pending(human)
        self.assertIsNone(human.submit(pending["id"], {"target": "ia_1"}))
        t.join(2)
        self.assertEqual(results[0]["action"]["target"], "ia_1")
        self.assertIsNone(human.pending)

    def test_stale_request_id_is_refused(self):
        human, results = HumanProvider(timeout_s=5), []
        t = self._ask_in_thread(human, ("k",), results)
        self._wait_pending(human)
        self.assertTrue(human.submit("nope", {"target": "ia_1"}))
        human.cancel()
        t.join(2)

    def test_timeout_returns_none_then_skips_waiting_for_same_key(self):
        human = HumanProvider(timeout_s=0.1)
        self.assertIsNone(human.ask(("k",), dict(VOTE)))
        start = time.monotonic()
        self.assertIsNone(human.ask(("k",), dict(VOTE)))  # 2e tentative du vote : immédiat
        self.assertLess(time.monotonic() - start, 0.05)

    def test_cancel_unblocks_ask(self):
        human, results = HumanProvider(timeout_s=30), []
        t = self._ask_in_thread(human, ("k",), results)
        self._wait_pending(human)
        human.cancel()
        t.join(2)
        self.assertEqual(results, [None])


class _StubAI:
    def get_action(self, player_id, context):
        return {"message": None, "action": None}


class RouterProviderTests(SimpleTestCase):
    """L'indicateur "X réfléchit" ne doit jamais trahir un rôle : la nuit,
    seuls les loups puis la sorcière sont appelés (jamais un villageois),
    donc nommer le joueur appelé la nuit révélerait son rôle à coup sûr.
    Le jour, tout le monde est appelé à chaque phase : nommer le joueur ne
    fuite rien."""

    def _ai_player_id(self, engine):
        return next(pid for pid, p in engine.state.players.items() if not p.is_human)

    def _router(self, engine, seen):
        return RouterProvider(
            engine, _StubAI(), human=None, stop=threading.Event(),
            on_thinking=lambda name: seen.append(name),
        )

    def test_night_calls_never_reveal_the_players_name(self):
        engine = GameEngine(rng=random.Random(1))
        engine.start("Umberto")
        ai_player_id = self._ai_player_id(engine)
        seen = []
        router = self._router(engine, seen)

        router.get_action(ai_player_id, {"phase": "nuit_loups"})
        router.get_action(ai_player_id, {"phase": "nuit_sorciere"})

        self.assertEqual(seen, [])

    def test_day_calls_reveal_the_players_name(self):
        engine = GameEngine(rng=random.Random(1))
        engine.start("Umberto")
        ai_player_id = self._ai_player_id(engine)
        pseudo = engine.state.players[ai_player_id].pseudo
        seen = []
        router = self._router(engine, seen)

        router.get_action(ai_player_id, {"phase": "jour_debat"})

        self.assertEqual(seen, [pseudo, None])


class BuildAIProviderTests(SimpleTestCase):
    """build_ai_provider ne doit activer le repli Groq que si une clé est
    configurée : sinon FallbackClient tenterait Groq pour rien à chaque appel
    OpenRouter raté."""

    def _state(self):
        engine = GameEngine(rng=random.Random(1))
        engine.start("Umberto")
        return engine.state

    def test_no_groq_key_uses_a_plain_openrouter_client(self):
        import os
        old = os.environ.pop("GROQ_API_KEY", None)
        try:
            provider = build_ai_provider(self._state(), fake=False)
            self.assertIsInstance(provider._client, OpenRouterClient)
        finally:
            if old is not None:
                os.environ["GROQ_API_KEY"] = old

    def test_groq_key_configured_wraps_openrouter_with_a_groq_fallback(self):
        import os
        old = os.environ.get("GROQ_API_KEY")
        os.environ["GROQ_API_KEY"] = "k"
        try:
            provider = build_ai_provider(self._state(), fake=False)
            self.assertIsInstance(provider._client, FallbackClient)
            self.assertIsInstance(provider._client.clients[0], OpenRouterClient)
            self.assertIsInstance(provider._client.clients[1], GroqClient)
        finally:
            if old is None:
                os.environ.pop("GROQ_API_KEY", None)
            else:
                os.environ["GROQ_API_KEY"] = old
