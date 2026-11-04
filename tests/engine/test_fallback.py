import random

from engine.fallback import pick_vote_fallback, pick_wolf_tiebreak


def test_pick_wolf_tiebreak_picks_among_proposed_candidates():
    result = pick_wolf_tiebreak(["ia_3", "ia_4"], ["ia_3", "ia_4", "ia_5"], rng=random.Random(1))
    assert result in {"ia_3", "ia_4"}


def test_pick_wolf_tiebreak_falls_back_to_any_alive_non_wolf_if_nobody_proposed():
    result = pick_wolf_tiebreak([], ["ia_3", "ia_4", "ia_5"], rng=random.Random(1))
    assert result in {"ia_3", "ia_4", "ia_5"}


def test_pick_vote_fallback_prefers_a_player_already_suspected():
    votes_so_far = {"ia_1": "ia_3", "ia_2": "ia_3"}
    result = pick_vote_fallback(votes_so_far, ["ia_1", "ia_2", "ia_3", "ia_4"], rng=random.Random(1))
    assert result == "ia_3"


def test_pick_vote_fallback_is_fully_random_when_nobody_has_voted_yet():
    result = pick_vote_fallback({}, ["ia_1", "ia_2", "ia_3"], rng=random.Random(1))
    assert result in {"ia_1", "ia_2", "ia_3"}
