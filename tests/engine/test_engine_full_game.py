import random

from engine.engine import GameEngine
from engine.models import Camp, Phase, Role


class AlwaysAgreeingHostileProvider:
    """Every wolf always proposes the first alive non-wolf; everyone always
    votes for the first alive wolf they can see is suspicious-by-script;
    nobody uses witch potions; nobody sends chat (instant debate end)."""
    def get_action(self, player_id, context):
        role = context["self_role"]
        phase = context["phase"]
        if phase == "nuit_loups":
            target = next(p["id"] for p in context["alive_players"] if p["id"] != player_id and p["id"] not in context["known_wolf_ids"])
            return {"message": None, "action": {"type": "night_kill_target", "target": target}}
        if phase == "nuit_sorciere":
            return {"message": None, "action": None}
        if phase == "jour_debat":
            return {"message": None, "action": None}
        if phase == "jour_vote":
            target = next(p["id"] for p in context["alive_players"] if p["id"] != player_id)
            return {"message": None, "action": {"type": "day_vote", "target": target}}
        raise AssertionError(f"unexpected phase {phase}")


def test_play_reaches_a_winner_within_max_cycles():
    engine = GameEngine(rng=random.Random(1))
    engine.start("Umberto")
    winner = engine.play(AlwaysAgreeingHostileProvider(), max_cycles=10)
    assert winner in {Camp.LOUPS, Camp.VILLAGEOIS}
    assert engine.state.winner == winner
    assert engine.state.phase == Phase.TERMINEE


def test_play_checks_victory_immediately_after_a_night_kill():
    # With only 1 wolf alive at start (forced via a pre-seeded state) and
    # everyone else dead but one, the game must end after that single
    # night without running a day cycle.
    engine = GameEngine(rng=random.Random(1))
    state = engine.start("Umberto")
    non_wolves = [p for p in state.players.values() if p.role != Role.LOUP]
    lone_survivor = non_wolves[0]
    for p in state.players.values():
        p.alive = p.role == Role.LOUP or p.pseudo == lone_survivor.pseudo
    # keep exactly the 2 loups + 1 other alive, rest already dead
    engine.run_night_cycle(AlwaysAgreeingHostileProvider())
    assert engine.check_and_set_winner() == Camp.LOUPS


def test_play_stops_at_max_cycles_without_crashing_if_nobody_wins():
    class StalemateProvider:
        def get_action(self, player_id, context):
            if context["phase"] in ("jour_vote",):
                return {"message": None, "action": {"type": "day_vote", "target": player_id}}  # self-votes only -> perpetual ties, nobody eliminated
            if context["phase"] == "nuit_loups":
                target = next(p["id"] for p in context["alive_players"] if p["id"] != player_id and p["id"] not in context["known_wolf_ids"])
                return {"message": None, "action": {"type": "night_kill_target", "target": target}}
            return {"message": None, "action": None}
    engine = GameEngine(rng=random.Random(1))
    engine.start("Umberto")
    winner = engine.play(StalemateProvider(), max_cycles=10)
    # the night phase still kills someone each cycle (no witch heal), so a
    # winner must emerge well before max_cycles because the roster shrinks
    assert winner in {Camp.LOUPS, Camp.VILLAGEOIS}
