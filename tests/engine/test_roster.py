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


class RecordingRandom(random.Random):
    def __init__(self, seed):
        super().__init__(seed)
        self.shuffle_lengths = []

    def shuffle(self, x):
        self.shuffle_lengths.append(len(x))
        super().shuffle(x)


def test_new_game_draws_roles_and_pairings_from_two_independent_shuffles():
    rng = RecordingRandom(1)
    roster.new_game("Umberto", rng=rng)
    assert sorted(rng.shuffle_lengths) == [5, 6]
    assert len(rng.shuffle_lengths) == 2


def test_new_game_gives_the_human_the_chosen_role():
    for role in (Role.LOUP, Role.SORCIERE, Role.VILLAGEOIS):
        state = roster.new_game("Umberto", rng=random.Random(1), human_role=role)
        assert state.players["human"].role == role


def test_new_game_with_a_chosen_role_keeps_the_overall_role_counts():
    for role in (Role.LOUP, Role.SORCIERE, Role.VILLAGEOIS):
        state = roster.new_game("Umberto", rng=random.Random(2), human_role=role)
        counts = Counter(p.role for p in state.players.values())
        assert counts == {Role.LOUP: 2, Role.SORCIERE: 1, Role.VILLAGEOIS: 3}


def test_new_game_without_a_chosen_role_is_still_random():
    roles = {roster.new_game("Umberto", rng=random.Random(s)).players["human"].role for s in range(30)}
    assert roles == {Role.LOUP, Role.SORCIERE, Role.VILLAGEOIS}
