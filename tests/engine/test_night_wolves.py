import random

from engine.models import GameState, Phase, Player, Role
from engine.night import resolve_wolf_phase


def make_state_with_wolves(*wolves: str, others: list[str]) -> GameState:
    players = {}
    for pid in wolves:
        players[pid] = Player(id=pid, pseudo=pid, is_human=False, role=Role.LOUP, personality=None)
    for pid in others:
        players[pid] = Player(id=pid, pseudo=pid, is_human=False, role=Role.VILLAGEOIS, personality=None)
    return GameState(players=players, phase=Phase.NUIT_LOUPS, cycle=1)


def action(target: str) -> dict:
    return {"message": None, "action": {"type": "night_kill_target", "target": target}}


class ScriptedWolfProvider:
    def __init__(self, scripts: dict[str, list[dict | None]]):
        self.scripts = scripts

    def get_action(self, player_id, context):
        return self.scripts[player_id].pop(0)


def test_wolves_agree_immediately_on_the_same_target():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4"])
    provider = ScriptedWolfProvider({
        "ia_1": [{"message": "ia_3", "action": {"type": "night_kill_target", "target": "ia_3"}}],
        "ia_2": [{"message": None, "action": {"type": "night_kill_target", "target": "ia_3"}}],
    })
    assert resolve_wolf_phase(state, provider, rng=random.Random(1)) == "ia_3"
    assert {"author": "ia_1", "text": "ia_3"} in state.wolf_room_log


def test_wolves_negotiate_up_to_three_rounds_then_agree():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4"])
    provider = ScriptedWolfProvider({
        "ia_1": [action("ia_3")] * 2 + [action("ia_4")],
        "ia_2": [action("ia_4")] * 3,
    })
    # ia_1 switches to ia_4 on round 3, matching ia_2
    assert resolve_wolf_phase(state, provider, rng=random.Random(1)) == "ia_4"


def test_wolves_still_disagreeing_after_three_rounds_triggers_tiebreak():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4"])
    provider = ScriptedWolfProvider({
        "ia_1": [action("ia_3")] * 3,
        "ia_2": [action("ia_4")] * 3,
    })
    result = resolve_wolf_phase(state, provider, rng=random.Random(1))
    assert result in {"ia_3", "ia_4"}


def test_a_wolf_attempting_to_target_the_other_wolf_is_treated_as_no_submission():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3"])
    provider = ScriptedWolfProvider({
        "ia_1": [action("ia_2")] * 3,   # illegal every round
        "ia_2": [action("ia_3")] * 3,
    })
    result = resolve_wolf_phase(state, provider, rng=random.Random(1))
    assert result == "ia_3"  # only legal candidate ever proposed


def test_silent_wolves_fall_back_to_a_random_alive_non_wolf():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4"])
    provider = ScriptedWolfProvider({"ia_1": [None] * 3, "ia_2": [None] * 3})
    result = resolve_wolf_phase(state, provider, rng=random.Random(1))
    assert result in {"ia_3", "ia_4"}
