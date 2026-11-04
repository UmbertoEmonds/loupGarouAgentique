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


def test_a_wolf_claiming_a_mismatched_action_type_is_treated_as_no_submission():
    # ia_1's response claims action.type "day_vote" (targeting ia_4) even
    # though the engine is asking for night_kill_target: this must not be
    # silently reinterpreted as a night-kill proposal on ia_4 just because
    # it carries a target the engine would otherwise accept. If it were
    # wrongly accepted, ia_1 and ia_2 would permanently disagree (ia_4 vs
    # ia_3) and the tiebreak could pick either; with the mismatch correctly
    # rejected, ia_1 never contributes, so ia_2's ia_3 is the only ever
    # valid proposal and wins deterministically regardless of rng seed.
    for seed in range(20):
        state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4"])
        provider = ScriptedWolfProvider({
            "ia_1": [{"message": None, "action": {"type": "day_vote", "target": "ia_4"}}] * 3,
            "ia_2": [action("ia_3")] * 3,
        })
        result = resolve_wolf_phase(state, provider, rng=random.Random(seed))
        assert result == "ia_3", f"seed {seed} let a mismatched action.type through as {result!r}"


def test_tiebreak_only_considers_each_wolfs_last_proposal_not_every_round():
    # Spec §2a: "le moteur tire au sort entre les deux dernières cibles
    # proposées". ia_1 proposes a DIFFERENT target every round (ia_3, then
    # ia_4, then ia_5) while ia_2 always proposes ia_6 (always disagreeing,
    # so agreement never happens and all 3 rounds run). The tiebreak must
    # only ever be able to choose between ia_1's LAST proposal (ia_5) and
    # ia_2's last proposal (ia_6) -- never ia_3 or ia_4, which were
    # abandoned proposals from earlier rounds.
    for seed in range(30):
        state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4", "ia_5", "ia_6"])
        provider = ScriptedWolfProvider({
            "ia_1": [action("ia_3"), action("ia_4"), action("ia_5")],
            "ia_2": [action("ia_6")] * 3,
        })
        result = resolve_wolf_phase(state, provider, rng=random.Random(seed))
        assert result in {"ia_5", "ia_6"}, f"seed {seed} picked abandoned proposal {result!r}"


def test_a_dead_wolf_is_never_asked_for_a_target_and_the_lone_survivor_can_agree_with_itself():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4"])
    state.get("ia_1").alive = False
    # ia_2's script has only one entry: if resolve_wolf_phase required all
    # 3 rounds (old behavior compared against the full 2-wolf roster), this
    # would raise IndexError on the second round. ia_1 has no script at
    # all: if it were ever called (dead wolf asked for a target), popping
    # from an empty list raises KeyError/IndexError immediately.
    provider = ScriptedWolfProvider({"ia_1": [], "ia_2": [action("ia_3")]})
    result = resolve_wolf_phase(state, provider, rng=random.Random(1))
    assert result == "ia_3"
