import os
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from monitoring.models import Game, RoundCost


class CostAdminTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "mdp")
        game = Game.objects.create(game_id="partie-1", started_at="2026-11-05T12:00:00Z")
        RoundCost.objects.create(game=game, round=1, calls=2, prompt_tokens=100,
                                 completion_tokens=20, total_tokens=120)
        RoundCost.objects.create(game=game, round=2, calls=1, prompt_tokens=10,
                                 completion_tokens=1, total_tokens=11)
        self.game = game

    def test_admin_requires_login(self):
        response = self.client.get("/admin/monitoring/game/")
        self.assertEqual(response.status_code, 302)

    def test_game_list_shows_totals_across_rounds(self):
        self.client.force_login(self.admin)
        response = self.client.get("/admin/monitoring/game/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "partie-1")
        self.assertContains(response, "131")  # 120 + 11 jetons

    def test_game_detail_and_round_list_are_viewable_but_read_only(self):
        self.client.force_login(self.admin)
        detail = self.client.get(f"/admin/monitoring/game/{self.game.pk}/change/")
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, 'name="_save"')
        self.assertEqual(self.client.get("/admin/monitoring/roundcost/").status_code, 200)
        self.assertEqual(self.client.get("/admin/monitoring/game/add/").status_code, 403)


class EnsureAdminCommandTests(TestCase):
    def _run(self, env):
        with mock.patch.dict(os.environ, env, clear=False):
            call_command("ensure_admin", stdout=StringIO())

    def test_creates_the_superuser_once(self):
        env = {"DJANGO_SUPERUSER_USERNAME": "boss", "DJANGO_SUPERUSER_PASSWORD": "secret"}
        self._run(env)
        self._run(env)  # deuxième build : rien ne change
        user = get_user_model().objects.get(username="boss")
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password("secret"))

    def test_does_nothing_without_credentials(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            call_command("ensure_admin", stdout=StringIO())
        self.assertFalse(get_user_model().objects.exists())
