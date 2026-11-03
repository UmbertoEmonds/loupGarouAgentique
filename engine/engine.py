from __future__ import annotations

import random
import time
from typing import Callable

from engine import day, night, roster, victory
from engine.models import Camp, GameState, Phase
from engine.provider import ActionProvider


class GameEngine:
    """Orchestrates a full game: night cycle -> victory check -> day cycle -> victory check."""

    def __init__(self, debate_duration_s: int = 180, rng: random.Random | None = None):
        self.debate_duration_s = debate_duration_s
        self.rng = rng or random.Random()
        self.state: GameState | None = None

    def start(self, human_pseudo: str) -> GameState:
        self.state = roster.new_game(human_pseudo, rng=self.rng)
        return self.state

    def run_night_cycle(self, provider: ActionProvider) -> list[str]:
        state = self.state

        state.phase = Phase.NUIT_LOUPS
        wolf_target = night.resolve_wolf_phase(state, provider, rng=self.rng)
        state.last_wolf_target = wolf_target

        state.phase = Phase.NUIT_SORCIERE
        healed, poisoned_id = night.resolve_witch_phase(state, provider, wolf_target)

        dead_ids = night.apply_night_deaths(state, wolf_target, healed, poisoned_id)

        if dead_ids:
            pseudos = ", ".join(state.players[pid].pseudo for pid in dead_ids)
            text = f"{pseudos} died during the night."
        else:
            text = "Nobody died during the night."
        state.main_room_log.append({"author": None, "text": text})

        return dead_ids

    def check_and_set_winner(self) -> Camp | None:
        state = self.state
        winner = victory.check_victory(state)
        if winner is not None:
            state.phase = Phase.TERMINEE
            state.winner = winner
        return winner

    def run_day_cycle(
        self,
        provider: ActionProvider,
        is_time_up: Callable[[], bool] | None = None,
    ) -> tuple[str | None, list[str]]:
        state = self.state

        if is_time_up is None:
            deadline = time.monotonic() + self.debate_duration_s
            is_time_up = lambda: time.monotonic() >= deadline

        state.phase = Phase.JOUR_DEBAT
        day.run_debate_round_robin(state, provider, is_time_up)

        state.phase = Phase.JOUR_VOTE
        votes, fallback_used = day.collect_votes(state, provider, rng=self.rng)
        eliminated = day.resolve_vote(votes, state.alive_ids())

        if eliminated is not None:
            state.players[eliminated].alive = False
            state.main_room_log.append(
                {"author": None, "text": f"{state.players[eliminated].pseudo} was voted out."}
            )

        return eliminated, fallback_used

    def play(self, provider: ActionProvider, max_cycles: int = 10) -> Camp | None:
        winner = self.check_and_set_winner()
        if winner is not None:
            return winner

        for _ in range(max_cycles):
            self.run_night_cycle(provider)
            winner = self.check_and_set_winner()
            if winner is not None:
                return winner

            self.run_day_cycle(provider)
            winner = self.check_and_set_winner()
            if winner is not None:
                return winner

            self.state.cycle += 1

        return self.state.winner
