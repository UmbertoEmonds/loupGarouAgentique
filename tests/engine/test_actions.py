import pytest

from engine.actions import Action, ActionInvalid, validate_action
from engine.models import ActionType, GameState, Phase, Player, Role


def make_state(roles: dict[str, Role], phase: Phase = Phase.NUIT_LOUPS) -> GameState:
    players = {
        pid: Player(id=pid, pseudo=pid, is_human=False, role=role, personality=None)
        for pid, role in roles.items()
    }
    return GameState(players=players, phase=phase, cycle=1)


def test_wolf_may_target_a_living_non_wolf():
    state = make_state({"ia_1": Role.LOUP, "ia_2": Role.LOUP, "ia_3": Role.VILLAGEOIS}, phase=Phase.NUIT_LOUPS)
    action = validate_action(state, "ia_1", ActionType.NIGHT_KILL_TARGET, "ia_3")
    assert action == Action(ActionType.NIGHT_KILL_TARGET, "ia_3")


def test_wolf_cannot_target_the_other_wolf():
    state = make_state({"ia_1": Role.LOUP, "ia_2": Role.LOUP, "ia_3": Role.VILLAGEOIS}, phase=Phase.NUIT_LOUPS)
    with pytest.raises(ActionInvalid):
        validate_action(state, "ia_1", ActionType.NIGHT_KILL_TARGET, "ia_2")


def test_villageois_cannot_submit_a_night_kill_target():
    state = make_state({"ia_1": Role.LOUP, "ia_3": Role.VILLAGEOIS}, phase=Phase.NUIT_LOUPS)
    with pytest.raises(ActionInvalid):
        validate_action(state, "ia_3", ActionType.NIGHT_KILL_TARGET, "ia_1")


def test_sorciere_cannot_submit_night_kill_target_instead_of_witch_action():
    state = make_state({"ia_1": Role.SORCIERE, "ia_2": Role.LOUP}, phase=Phase.NUIT_SORCIERE)
    with pytest.raises(ActionInvalid):
        validate_action(state, "ia_1", ActionType.NIGHT_KILL_TARGET, "ia_2")


def test_witch_heal_must_target_the_wolves_victim():
    state = make_state({"ia_1": Role.SORCIERE, "ia_2": Role.VILLAGEOIS}, phase=Phase.NUIT_SORCIERE)
    state.last_wolf_target = "ia_2"
    validate_action(state, "ia_1", ActionType.WITCH_HEAL, "ia_2")  # does not raise
    with pytest.raises(ActionInvalid):
        validate_action(state, "ia_1", ActionType.WITCH_HEAL, "ia_1")


def test_witch_cannot_heal_herself_even_if_she_is_the_victim():
    state = make_state({"ia_1": Role.SORCIERE, "ia_2": Role.VILLAGEOIS}, phase=Phase.NUIT_SORCIERE)
    state.last_wolf_target = "ia_1"
    with pytest.raises(ActionInvalid):
        validate_action(state, "ia_1", ActionType.WITCH_HEAL, "ia_1")


def test_witch_poison_may_target_anyone_including_herself():
    state = make_state({"ia_1": Role.SORCIERE, "ia_2": Role.VILLAGEOIS}, phase=Phase.NUIT_SORCIERE)
    validate_action(state, "ia_1", ActionType.WITCH_POISON, "ia_1")  # does not raise
    validate_action(state, "ia_1", ActionType.WITCH_POISON, "ia_2")  # does not raise


def test_declining_a_witch_potion_is_always_legal():
    state = make_state({"ia_1": Role.SORCIERE}, phase=Phase.NUIT_SORCIERE)
    validate_action(state, "ia_1", ActionType.WITCH_HEAL, None)
    validate_action(state, "ia_1", ActionType.WITCH_POISON, None)


def test_day_vote_self_vote_is_allowed():
    state = make_state({"ia_1": Role.VILLAGEOIS}, phase=Phase.JOUR_VOTE)
    validate_action(state, "ia_1", ActionType.DAY_VOTE, "ia_1")  # does not raise


def test_day_vote_target_must_be_alive():
    state = make_state({"ia_1": Role.VILLAGEOIS, "ia_2": Role.VILLAGEOIS}, phase=Phase.JOUR_VOTE)
    state.players["ia_2"].alive = False
    with pytest.raises(ActionInvalid):
        validate_action(state, "ia_1", ActionType.DAY_VOTE, "ia_2")


def test_dead_player_cannot_submit_any_action():
    state = make_state({"ia_1": Role.VILLAGEOIS, "ia_2": Role.VILLAGEOIS}, phase=Phase.JOUR_VOTE)
    state.players["ia_1"].alive = False
    with pytest.raises(ActionInvalid):
        validate_action(state, "ia_1", ActionType.DAY_VOTE, "ia_2")
