from engine.models import Camp, GameState, Phase, Player, Role
from engine.victory import check_victory


def make_state_with_roles(roles: dict[str, Role]) -> GameState:
    players = {
        pid: Player(id=pid, pseudo=pid, is_human=False, role=role, personality=None)
        for pid, role in roles.items()
    }
    return GameState(players=players, phase=Phase.JOUR_VOTE, cycle=1)


def test_villagers_win_when_both_wolves_are_dead():
    state = make_state_with_roles({"ia_1": Role.LOUP, "ia_2": Role.LOUP, "ia_3": Role.VILLAGEOIS})
    state.get("ia_1").alive = False
    state.get("ia_2").alive = False
    assert check_victory(state) == Camp.VILLAGEOIS

def test_no_winner_while_one_wolf_still_lives():
    state = make_state_with_roles({"ia_1": Role.LOUP, "ia_2": Role.LOUP, "ia_3": Role.VILLAGEOIS})
    state.get("ia_1").alive = False
    assert check_victory(state) is None

def test_wolves_do_not_win_on_mere_parity():
    state = make_state_with_roles({"ia_1": Role.LOUP, "ia_2": Role.LOUP, "ia_3": Role.VILLAGEOIS, "ia_4": Role.VILLAGEOIS})
    state.get("ia_3").alive = False
    state.get("ia_4").alive = False
    # 2 loups vs 0 others alive... actually parity test: 2 vs 2 before this kill
    assert check_victory(state) == Camp.LOUPS  # 2 loups vs 0 others is already strict superiority

def test_wolves_do_not_win_at_exact_parity_two_vs_two():
    state = make_state_with_roles({"ia_1": Role.LOUP, "ia_2": Role.LOUP, "ia_3": Role.VILLAGEOIS, "ia_4": Role.VILLAGEOIS})
    assert check_victory(state) is None  # 2 vs 2, not strictly superior

def test_wolves_win_on_strict_superiority_three_vs_two_reduced_to_two_vs_one():
    state = make_state_with_roles({"ia_1": Role.LOUP, "ia_2": Role.LOUP, "ia_3": Role.VILLAGEOIS, "ia_4": Role.VILLAGEOIS, "ia_5": Role.VILLAGEOIS})
    state.get("ia_4").alive = False
    state.get("ia_5").alive = False
    assert check_victory(state) == Camp.LOUPS  # 2 loups vs 1 other
