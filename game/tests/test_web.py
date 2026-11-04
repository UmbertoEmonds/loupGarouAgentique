import time

from channels.testing import WebsocketCommunicator
from django.test import Client, SimpleTestCase, override_settings

from config.asgi import application
from game.session import session

FAST = dict(FAKE_AI=True, FAKE_AI_DELAY_S=0, PHASE_PAUSE_S=0, HUMAN_TIMEOUT_S=30, DEBATE_DURATION_S=5)


@override_settings(**FAST)
class ViewTests(SimpleTestCase):
    def setUp(self):
        session.abandon()
        session.reset()

    def tearDown(self):
        session.abandon()

    def test_home_renders(self):
        self.assertContains(Client().get("/"), "Commencer une partie")

    def test_play_redirects_without_game(self):
        self.assertEqual(Client().get("/jouer/").status_code, 302)

    def test_empty_pseudo_is_refused(self):
        resp = Client().post("/nouvelle-partie/", {"pseudo": "  "})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("erreur=pseudo", resp["Location"])

    def test_play_page_shows_ai_warning(self):
        owner = Client()
        owner.post("/nouvelle-partie/", {"pseudo": "Alice"})
        self.assertContains(owner.get("/jouer/"), "Tous les autres joueurs sont des IA")

    def test_second_visitor_sees_game_in_progress(self):
        owner, other = Client(), Client()
        self.assertEqual(owner.post("/nouvelle-partie/", {"pseudo": "Alice"}).status_code, 302)
        self.assertEqual(owner.get("/jouer/").status_code, 200)
        self.assertContains(other.get("/"), "Partie déjà en cours")
        self.assertEqual(other.get("/jouer/").status_code, 302)
        self.assertIn("erreur=occupe", other.post("/nouvelle-partie/", {"pseudo": "Bob"})["Location"])


@override_settings(**FAST)
class WebSocketTests(SimpleTestCase):
    def setUp(self):
        session.abandon()
        session.reset()

    def tearDown(self):
        session.abandon()

    def _communicator(self, client):
        cookie = client.cookies["sessionid"].value
        headers = [(b"origin", b"http://testserver"), (b"cookie", f"sessionid={cookie}".encode())]
        return WebsocketCommunicator(application, "/ws/game/", headers=headers)

    async def test_stranger_is_rejected(self):
        comm = WebsocketCommunicator(application, "/ws/game/", headers=[(b"origin", b"http://testserver")])
        connected, _ = await comm.connect()
        self.assertFalse(connected)

    async def test_owner_receives_state_and_can_answer(self):
        from asgiref.sync import sync_to_async

        client = Client()
        await sync_to_async(client.post)("/nouvelle-partie/", {"pseudo": "Alice"})
        comm = self._communicator(client)
        connected, _ = await comm.connect()
        self.assertTrue(connected)

        first = await comm.receive_json_from()
        self.assertEqual(first["type"], "state")
        self.assertEqual(first["payload"]["me"]["pseudo"], "Alice")

        # Réponds à chaque demande de l'humain jusqu'à la fin de partie.
        answered = 0
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            msg = await comm.receive_json_from(timeout=15)
            payload = msg["payload"]
            if payload["phase"] == "terminee":
                break
            pending = payload["pending"]
            if not pending:
                continue
            reply = {"type": "answer", "request_id": pending["id"], "message": "bonjour", "accept": False}
            if pending["targets"] and pending["kind"] in ("vote", "wolf_kill"):
                reply.update(target=pending["targets"][0]["id"], accept=True)
            await comm.send_json_to(reply)
            answered += 1
        else:
            self.fail("la partie ne s'est pas terminée")
        # Les rôles sont aléatoires : un humain tué dès la nuit 1 n'est jamais sollicité.
        self.assertTrue(answered > 0 or not payload["me"]["alive"])
        self.assertIn(payload["winner"], ("loups", "villageois"))
        await comm.disconnect()


class HomeWarningTests(SimpleTestCase):
    def test_home_warns_that_all_other_players_are_ai(self):
        self.assertContains(Client().get("/"), "tous les autres joueurs sont des IA")


class PrivacyPageTests(SimpleTestCase):
    def test_privacy_page_covers_rgpd_and_ai_act(self):
        resp = Client().get("/confidentialite/")
        self.assertEqual(resp.status_code, 200)
        for text in ("RGPD", "AI Act", "sessionid", "csrftoken", "OpenRouter", "Groq", "CNIL"):
            self.assertContains(resp, text)

    def test_contact_email_shown_only_when_configured(self):
        self.assertNotContains(Client().get("/confidentialite/"), "mailto:")
        with override_settings(PRIVACY_CONTACT_EMAIL="privacy@example.org"):
            self.assertContains(Client().get("/confidentialite/"), "mailto:privacy@example.org")

    def test_home_links_to_privacy_page(self):
        resp = Client().get("/")
        self.assertContains(resp, "/confidentialite/")
        self.assertContains(resp, "en savoir plus sur la confidentialité et l'usage des données")
