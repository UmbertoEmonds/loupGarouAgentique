import random
from collections import Counter

from engine import roster
from engine.models import Phase, Role


def test_new_game_has_six_players_with_correct_role_counts():
    state = roster.new_game("Umberto", rng=random.Random(1))
    assert len(state.players) == 6
    counts = Counter(p.role for p in state.players.values())
    assert counts == {Role.LOUP: 2, Role.SORCIERE: 1, Role.VILLAGEOIS: 3}


def test_new_game_includes_the_human_exactly_once():
    state = roster.new_game("Umberto", rng=random.Random(1))
    humans = [p for p in state.players.values() if p.is_human]
    assert len(humans) == 1
    assert humans[0].pseudo == "Umberto"
    assert humans[0].personality is None


def test_new_game_gives_each_ai_a_distinct_prenom_and_personality():
    state = roster.new_game("Umberto", rng=random.Random(1))
    ai_players = [p for p in state.players.values() if not p.is_human]
    assert len(ai_players) == 5
    assert sorted(p.pseudo for p in ai_players) == sorted(roster.PRENOMS)
    assert sorted(p.personality for p in ai_players) == sorted(roster.PERSONNALITES)


def test_new_game_randomizes_role_and_name_assignment_across_seeds():
    state_a = roster.new_game("Umberto", rng=random.Random(1))
    state_b = roster.new_game("Umberto", rng=random.Random(2))
    roles_a = sorted((p.pseudo, p.role) for p in state_a.players.values())
    roles_b = sorted((p.pseudo, p.role) for p in state_b.players.values())
    assert roles_a != roles_b


def test_new_game_starts_at_night_phase_cycle_one():
    state = roster.new_game("Umberto", rng=random.Random(1))
    assert state.phase == Phase.NUIT_LOUPS
    assert state.cycle == 1
