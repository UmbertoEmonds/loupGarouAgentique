"""Ce que le village sait publiquement : rôle des morts et votes du jour."""
import random

from engine.context import build_context
from engine.engine import GameEngine
from engine.models import GameState, Phase, Player, Role


def make_state() -> GameState:
    players = {
        "human": Player(id="human", pseudo="Capucine", is_human=True, role=Role.VILLAGEOIS, personality=None),
        "ia_1": Player(id="ia_1", pseudo="Sarah", is_human=False, role=Role.LOUP, personality=None),
        "ia_2": Player(id="ia_2", pseudo="Benji", is_human=False, role=Role.SORCIERE, personality=None),
        "ia_3": Player(id="ia_3", pseudo="Ines", is_human=False, role=Role.VILLAGEOIS, personality=None),
    }
    return GameState(players=players, phase=Phase.JOUR_DEBAT, cycle=1)


def test_every_player_sees_the_revealed_role_of_the_dead():
    state = make_state()
    state.players["ia_1"].alive = False
    context = build_context(state, state.players["ia_3"], [])
    assert context["dead_players"] == [{"id": "ia_1", "pseudo": "Sarah", "role": "loup"}]


def test_no_dead_player_means_an_empty_list():
    state = make_state()
    assert build_context(state, state.players["ia_3"], [])["dead_players"] == []


class VoteFor:
    def __init__(self, choices):
        self.choices = choices

    def get_action(self, player_id, context):
        if context["phase"] == "jour_vote":
            return {"message": None, "action": {"type": "day_vote", "target": self.choices[player_id]}}
        return {"message": None, "action": None}


def _engine(state):
    engine = GameEngine(rng=random.Random(1))
    engine.state = state
    return engine


def test_votes_are_announced_publicly_before_the_result():
    state = make_state()
    _engine(state).run_day_cycle(
        VoteFor({"human": "ia_1", "ia_1": "ia_3", "ia_2": "ia_1", "ia_3": "ia_1"}), is_time_up=lambda: True
    )
    texts = [e["text"] for e in state.main_room_log if e["author"] is None]
    assert texts == [
        "🗳️ Votes : Capucine → Sarah, Sarah → Ines, Benji → Sarah, Ines → Sarah.",
        "Sarah a été éliminé par le vote.",
    ]


def test_a_tie_is_announced():
    state = make_state()
    _engine(state).run_day_cycle(
        VoteFor({"human": "ia_1", "ia_1": "ia_3", "ia_2": "ia_1", "ia_3": "ia_3"}), is_time_up=lambda: True
    )
    assert state.main_room_log[-1] == {"author": None, "text": "Égalité : personne n'est éliminé aujourd'hui."}
