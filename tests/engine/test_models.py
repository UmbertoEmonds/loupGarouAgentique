from engine.models import GameState, Phase, Player, Role


def test_player_defaults_alive_and_potions_unused():
    p = Player(id="ia_1", pseudo="Fatima", is_human=False, role=Role.VILLAGEOIS, personality="stratege")
    assert p.alive is True
    assert p.witch_heal_used is False
    assert p.witch_poison_used is False


def test_gamestate_alive_ids_excludes_dead_players():
    players = {
        "human": Player(id="human", pseudo="Umberto", is_human=True, role=Role.VILLAGEOIS, personality=None),
        "ia_1": Player(id="ia_1", pseudo="Sofia", is_human=False, role=Role.LOUP, personality="impatient", alive=False),
    }
    state = GameState(players=players, phase=Phase.NUIT_LOUPS, cycle=1)
    assert state.alive_ids() == ["human"]


def test_gamestate_wolves_returns_only_loup_role():
    players = {
        "ia_1": Player(id="ia_1", pseudo="Ethan", is_human=False, role=Role.LOUP, personality="manipulateur"),
        "ia_2": Player(id="ia_2", pseudo="Elliot", is_human=False, role=Role.SORCIERE, personality="paranoiaque"),
    }
    state = GameState(players=players, phase=Phase.NUIT_LOUPS, cycle=1)
    assert [p.id for p in state.wolves()] == ["ia_1"]
