"""Le salon des loups ne doit jamais atteindre un non-loup, ni le salon principal."""
import random

from engine.engine import GameEngine
from engine.models import Role

WOLF_SECRET = "SECRET-LOUPS"


class RecordingProvider:
    """Les loups parlent en privé la nuit avec un marqueur ; tout le monde
    garde le contexte reçu pour que le test l'inspecte ensuite."""

    def __init__(self):
        self.contexts: list[tuple[str, dict]] = []

    def get_action(self, player_id, context):
        self.contexts.append((player_id, context))
        phase = context["phase"]
        if phase == "nuit_loups":
            target = next(
                p["id"] for p in context["alive_players"]
                if p["id"] != player_id and p["id"] not in context["known_wolf_ids"]
            )
            return {"message": f"{WOLF_SECRET} {player_id}",
                    "action": {"type": "night_kill_target", "target": target}}
        if phase == "jour_vote":
            target = next(p["id"] for p in context["alive_players"] if p["id"] != player_id)
            return {"message": None, "action": {"type": "day_vote", "target": target}}
        return {"message": None, "action": None}


def _play():
    engine = GameEngine(rng=random.Random(3))
    engine.start("Umberto")
    provider = RecordingProvider()
    engine.play(provider, max_cycles=10)
    return engine, provider


def test_wolf_room_text_never_reaches_the_main_room():
    engine, _ = _play()
    assert engine.state.wolf_room_log  # le test est vide de sens sinon
    assert all(WOLF_SECRET not in e["text"] for e in engine.state.main_room_log)


def test_non_wolves_never_receive_the_wolf_room_or_the_wolf_list():
    engine, provider = _play()
    for player_id, context in provider.contexts:
        if engine.state.get(player_id).role == Role.LOUP:
            continue
        assert context["wolf_room_log"] is None
        assert context["known_wolf_ids"] == []
        assert WOLF_SECRET not in repr(context)


def test_wolves_do_receive_the_wolf_room():
    engine, provider = _play()
    assert any(
        context["wolf_room_log"]
        for player_id, context in provider.contexts
        if engine.state.get(player_id).role == Role.LOUP
    )
