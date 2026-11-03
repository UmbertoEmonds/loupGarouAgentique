import random

from engine.day import collect_votes, resolve_vote, run_debate_round_robin
from engine.models import GameState, Phase, Player, Role


def make_state_with_alive(*ids: str) -> GameState:
    players = {
        pid: Player(id=pid, pseudo=pid, is_human=False, role=Role.VILLAGEOIS, personality=None)
        for pid in ids
    }
    return GameState(players=players, phase=Phase.JOUR_DEBAT, cycle=1)


class ScriptedProvider:
    def __init__(self, scripts: dict[str, list[dict | None]]):
        self.scripts = scripts

    def get_action(self, player_id, context):
        return self.scripts[player_id].pop(0)


def test_debate_stops_when_time_is_up_before_any_pass():
    state = make_state_with_alive("ia_1", "ia_2")
    provider = ScriptedProvider({"ia_1": [], "ia_2": []})
    run_debate_round_robin(state, provider, is_time_up=lambda: True)
    assert state.main_room_log == []


def test_debate_records_messages_and_resets_pass_streak():
    state = make_state_with_alive("ia_1", "ia_2")
    calls = {"n": 0}

    def is_time_up():
        calls["n"] += 1
        return calls["n"] > 4  # allow two full passes

    provider = ScriptedProvider({
        "ia_1": [{"message": "salut", "action": None}, {"message": None, "action": None}],
        "ia_2": [{"message": None, "action": None}, {"message": None, "action": None}],
    })
    run_debate_round_robin(state, provider, is_time_up=is_time_up)
    assert {"author": "ia_1", "text": "salut"} in state.main_room_log


def test_debate_stops_early_on_one_full_round_of_passes():
    state = make_state_with_alive("ia_1", "ia_2")
    provider = ScriptedProvider({
        "ia_1": [{"message": None, "action": None}] * 5,
        "ia_2": [{"message": None, "action": None}] * 5,
    })
    run_debate_round_robin(state, provider, is_time_up=lambda: False)
    assert state.main_room_log == []  # stopped after round 1, never reached time-up


def test_collect_votes_records_a_valid_vote_including_self_vote():
    state = make_state_with_alive("ia_1", "ia_2")
    provider = ScriptedProvider({
        "ia_1": [{"message": None, "action": {"type": "day_vote", "target": "ia_1"}}],
        "ia_2": [{"message": None, "action": {"type": "day_vote", "target": "ia_1"}}],
    })
    votes, fallback_used = collect_votes(state, provider, rng=random.Random(1))
    assert votes == {"ia_1": "ia_1", "ia_2": "ia_1"}
    assert fallback_used == []


def test_collect_votes_falls_back_after_retry_exhausted():
    state = make_state_with_alive("ia_1", "ia_2", "ia_3")
    provider = ScriptedProvider({
        "ia_1": [{"message": None, "action": {"type": "day_vote", "target": "ia_2"}}],
        "ia_2": [{"message": None, "action": {"type": "day_vote", "target": "ia_2"}}],
        "ia_3": [None, None],
    })
    votes, fallback_used = collect_votes(state, provider, rng=random.Random(1))
    assert fallback_used == ["ia_3"]
    assert votes["ia_3"] == "ia_2"  # ia_2 already has votes, so the "suspected" pool picks it


def test_collect_votes_fallback_is_random_when_nobody_voted_yet():
    state = make_state_with_alive("ia_1", "ia_2")
    provider = ScriptedProvider({"ia_1": [None, None], "ia_2": [None, None]})
    votes, fallback_used = collect_votes(state, provider, rng=random.Random(1))
    assert set(fallback_used) == {"ia_1", "ia_2"}
    assert all(v in {"ia_1", "ia_2"} for v in votes.values())


def test_resolve_vote_eliminates_the_clear_majority():
    assert resolve_vote({"a": "c", "b": "c", "c": "a"}, ["a", "b", "c"]) == "c"


def test_resolve_vote_two_way_tie_eliminates_nobody():
    assert resolve_vote({"a": "b", "b": "a"}, ["a", "b"]) is None


def test_resolve_vote_three_way_tie_eliminates_nobody():
    assert resolve_vote({"a": "d", "b": "e", "c": "f", "d": "a", "e": "b", "f": "c"},
                         ["a", "b", "c", "d", "e", "f"]) is None


def test_known_wolf_ids_in_day_context_excludes_dead_wolves():
    players = {
        "ia_1": Player(id="ia_1", pseudo="ia_1", is_human=False, role=Role.LOUP, personality=None),
        "ia_2": Player(id="ia_2", pseudo="ia_2", is_human=False, role=Role.LOUP, personality=None, alive=False),
        "ia_3": Player(id="ia_3", pseudo="ia_3", is_human=False, role=Role.VILLAGEOIS, personality=None),
    }
    state = GameState(players=players, phase=Phase.JOUR_DEBAT, cycle=1)
    captured_contexts = []

    class RecordingProvider:
        def get_action(self, player_id, context):
            captured_contexts.append((player_id, context))
            return {"message": None, "action": None}

    run_debate_round_robin(state, RecordingProvider(), is_time_up=lambda: False)

    ia_1_context = next(ctx for pid, ctx in captured_contexts if pid == "ia_1")
    assert ia_1_context["known_wolf_ids"] == []
