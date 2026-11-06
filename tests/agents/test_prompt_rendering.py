"""Rend le prompt complet (système + message du tour) de chaque rôle à chaque phase.

But : relire d'un coup ce que voit vraiment le modèle avant de modifier une
règle du prompt, en particulier dans les cas sans information (nuit 1,
historique vide), que l'audit du 2026-11-06 n'avait pas vérifiés.

Pour afficher tous les prompts :
    PRINT_PROMPTS=1 python3 -m pytest tests/agents/test_prompt_rendering.py -s
"""

import os
import random

import pytest

from agents.provider import AIActionProvider
from engine import roster
from engine.context import build_context
from engine.models import ActionType, Phase, Role

NARRATOR_NIGHT = {"author": None, "text": "🌙 La nuit tombe, le village s'endort…"}
FIRST_NIGHT_NOTE = "C'est la première nuit"


def _game():
    state = roster.new_game("Capucine", rng=random.Random(7), human_role=Role.LOUP)
    ia = {pid: p for pid, p in state.players.items() if not p.is_human}
    provider = AIActionProvider(
        client=None,
        player_names={pid: p.pseudo for pid, p in ia.items()},
        player_roles={pid: p.role for pid, p in ia.items()},
        player_personalities={pid: p.personality for pid, p in ia.items()},
    )
    # Comme build_ai_provider : le pseudo de l'humain reste lisible dans l'historique.
    provider._player_names["human"] = "Capucine"
    return state, provider


def _ai_with_role(state, role):
    return next(p for p in state.players.values() if not p.is_human and p.role == role)


def _scenarios():
    """(nom, phase, rôle appelé, historique du salon principal, salon loups, actions)."""
    night_1_wolves = [{"author": None, "text": "🌙 Nuit 1"}, {"author": None, "text": "Tour de concertation 1/3."}]
    day_1 = [NARRATOR_NIGHT, {"author": None, "text": "☀️ Le jour se lève, le village se réveille…"},
             {"author": None, "text": "Personne n'est mort cette nuit."}]
    day_1_spoken = day_1 + [{"author": "human", "text": "Qui a une piste ?"}]
    return [
        ("nuit 1 - loups", Phase.NUIT_LOUPS, Role.LOUP, [NARRATOR_NIGHT], night_1_wolves,
         [ActionType.NIGHT_KILL_TARGET.value]),
        ("nuit 1 - sorcière (soin)", Phase.NUIT_SORCIERE, Role.SORCIERE, [NARRATOR_NIGHT], [],
         [ActionType.WITCH_HEAL.value]),
        ("jour 1 - débat, premier à parler", Phase.JOUR_DEBAT, Role.VILLAGEOIS, day_1, [], []),
        ("jour 1 - débat, loup", Phase.JOUR_DEBAT, Role.LOUP, day_1_spoken, night_1_wolves, []),
        ("jour 1 - vote", Phase.JOUR_VOTE, Role.VILLAGEOIS, day_1_spoken, [], [ActionType.DAY_VOTE.value]),
        ("nuit 2 - loups", Phase.NUIT_LOUPS, Role.LOUP, day_1_spoken, night_1_wolves,
         [ActionType.NIGHT_KILL_TARGET.value]),
    ]


def _render(name, phase, role, main_log, wolf_log, actions):
    state, provider = _game()
    state.phase = phase
    state.main_room_log = list(main_log)
    state.wolf_room_log = list(wolf_log)
    player = _ai_with_role(state, role)
    wolf_target = "human" if phase == Phase.NUIT_SORCIERE else None
    context = build_context(state, player, actions, wolf_target_tonight=wolf_target)
    system = provider._system_prompts[player.id]
    user = provider._build_user_content(player.id, context)
    if os.environ.get("PRINT_PROMPTS"):
        print(f"\n{'=' * 80}\n{name} — {player.pseudo} ({role.value}, {player.personality})\n{'=' * 80}")
        print(f"--- SYSTÈME ---\n{system}\n--- TOUR ---\n{user}")
    return system, user


@pytest.mark.parametrize("scenario", _scenarios(), ids=lambda s: s[0])
def test_every_phase_renders_a_prompt(scenario):
    system, user = _render(*scenario)
    assert system and user
    assert "Phase actuelle" in user


def test_first_night_wolf_is_told_nobody_has_spoken_yet():
    _, user = _render(*_scenarios()[0])
    assert FIRST_NIGHT_NOTE in user


def test_later_nights_drop_the_first_night_note():
    _, user = _render(*_scenarios()[-1])
    assert FIRST_NIGHT_NOTE not in user


@pytest.mark.parametrize("scenario", [s for s in _scenarios() if s[2] != Role.LOUP], ids=lambda s: s[0])
def test_non_wolves_never_see_the_wolf_room(scenario):
    _, user = _render(*scenario)
    assert "[Salon loups]" not in user
    assert "Tour de concertation" not in user


def test_first_night_witch_is_told_she_has_no_clue_before_poisoning():
    # Partie réelle du 2026-11-06 : la sorcière a empoisonné Sarah dès la
    # nuit 1 (« je soupçonne Sarah ») alors que personne n'avait parlé.
    name, phase, role, main_log, wolf_log, _ = _scenarios()[1]
    _, user = _render(name, phase, role, main_log, wolf_log, [ActionType.WITCH_POISON.value])
    assert "aucun indice" in user


def test_witch_heal_and_later_poison_have_no_first_night_note():
    _, heal = _render(*_scenarios()[1])
    day_log = _scenarios()[4][3]
    _, poison = _render("nuit 2 - sorcière", Phase.NUIT_SORCIERE, Role.SORCIERE, day_log, [],
                        [ActionType.WITCH_POISON.value])
    assert "aucun indice" not in heal
    assert "aucun indice" not in poison
