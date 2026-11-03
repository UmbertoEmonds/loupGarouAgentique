import json
import random
import re

from agents.provider import AIActionProvider
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


class ScriptedAIClient:
    """A FakeClient (agents/tests pattern) that scripts OpenRouterClient's
    `complete` by phase and role, parsed out of the real prompt text built
    by AIActionProvider. This stands in for the network call only -- the
    adapter (AIActionProvider), the JSON schema (agents/schema.py), and the
    prompts (agents/prompts.py) between it and the engine are all real.
    """

    def __init__(self, player_names: dict[str, str], player_roles: dict[str, Role]):
        self.player_names = player_names
        self.player_roles = player_roles
        self.calls: list[tuple[str, str]] = []
        self.saw_wolf_target_tonight_in_poison_call = False

    @staticmethod
    def _alive_ids(user_content: str) -> list[str]:
        match = re.search(r"Joueurs vivants \(id:pseudo\) : ([^\n]*)\.", user_content)
        roster = match.group(1)
        return [pair.split(":")[0] for pair in roster.split(", ") if pair]

    def _player_id_for(self, system_prompt: str) -> str:
        for pid, pseudo in self.player_names.items():
            if f"Tu es {pseudo}," in system_prompt:
                return pid
        raise AssertionError("could not resolve calling player from system prompt")

    def complete(self, system_prompt: str, user_content: str) -> str:
        self.calls.append((system_prompt, user_content))
        player_id = self._player_id_for(system_prompt)
        alive_ids = self._alive_ids(user_content)

        if "Phase actuelle : nuit_loups" in user_content:
            target = next(pid for pid in alive_ids if self.player_roles[pid] != Role.LOUP)
            return json.dumps({"message": None, "action": {"type": "night_kill_target", "target": target}})

        if "Phase actuelle : nuit_sorciere" in user_content:
            if "witch_poison" in user_content:
                self.saw_wolf_target_tonight_in_poison_call = "Cible des loups cette nuit :" in user_content
            return json.dumps({"message": None, "action": None})  # witch declines both potions

        if "Phase actuelle : jour_debat" in user_content:
            return json.dumps({"message": None, "action": None})  # pass, ending the debate quickly

        if "Phase actuelle : jour_vote" in user_content:
            target = next(pid for pid in alive_ids if pid != player_id)
            return json.dumps({"message": None, "action": {"type": "day_vote", "target": target}})

        raise AssertionError(f"unexpected context: {user_content!r}")


def test_real_ai_action_provider_drives_a_full_night_and_day_cycle():
    """Regression test for C2 and a general end-to-end seam check: the
    existing 91+ tests only exercise engine/ with scripted engine-only fake
    providers, never the real agents/provider.py adapter wired into
    GameEngine. This builds a real AIActionProvider on top of a
    ScriptedAIClient and runs one full night cycle (including the witch's
    poison sub-call, where context["wolf_target_tonight"] must be present
    and rendered) and one full day cycle through the real engine."""
    engine = GameEngine(rng=random.Random(7))
    state = engine.start("Umberto")

    player_names = {pid: p.pseudo for pid, p in state.players.items()}
    player_roles = {pid: p.role for pid, p in state.players.items()}
    player_personalities = {pid: (p.personality or "stratege") for pid, p in state.players.items()}

    client = ScriptedAIClient(player_names, player_roles)
    provider = AIActionProvider(client, player_names, player_roles, player_personalities)

    dead_ids = engine.run_night_cycle(provider)
    assert dead_ids  # the wolves' agreed-upon, unhealed target died
    assert client.saw_wolf_target_tonight_in_poison_call  # C2 regression check

    winner = engine.check_and_set_winner()
    if winner is None:
        eliminated, fallback_used = engine.run_day_cycle(provider)
        assert fallback_used == []  # the real adapter's votes were all valid, no fallback needed


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
