from __future__ import annotations

import random
import time
from typing import Callable

from engine import day, night, roster, victory
from engine.models import Camp, GameState, Phase
from engine.provider import ActionProvider


class GameEngine:
    """Orchestre une partie complète : cycle de nuit -> vérification de victoire -> cycle de jour -> vérification de victoire."""

    def __init__(self, debate_duration_s: int = 180, rng: random.Random | None = None):
        self.debate_duration_s = debate_duration_s
        self.rng = rng or random.Random()
        self.state: GameState | None = None

    def start(self, human_pseudo: str) -> GameState:
        self.state = roster.new_game(human_pseudo, rng=self.rng)
        return self.state

    def run_night_cycle(self, provider: ActionProvider) -> list[str]:
        state = self.state

        # Le village s'endort : la nuit commence, les loups se réveillent
        # en premier et se concertent en privé sur leur victime.
        state.phase = Phase.NUIT_LOUPS
        wolf_target = night.resolve_wolf_phase(state, provider, rng=self.rng)
        state.last_wolf_target = wolf_target

        # La sorcière se réveille à son tour, découvre la cible des loups
        # et décide d'utiliser, ou non, sa potion de soin et/ou de poison.
        state.phase = Phase.NUIT_SORCIERE
        healed, poisoned_id = night.resolve_witch_phase(state, provider, wolf_target)

        # Le village se réveille : on calcule qui est réellement mort
        # cette nuit (soin et poison pris en compte) et on l'annonce.
        dead_ids = night.apply_night_deaths(state, wolf_target, healed, poisoned_id)

        if dead_ids:
            pseudos = ", ".join(state.players[pid].pseudo for pid in dead_ids)
            text = f"{pseudos} est mort cette nuit." if len(dead_ids) == 1 else f"{pseudos} sont morts cette nuit."
        else:
            text = "Personne n'est mort cette nuit."
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

        # Le village débat publiquement de ce qui s'est passé cette nuit.
        state.phase = Phase.JOUR_DEBAT
        day.run_debate_round_robin(state, provider, is_time_up)

        # Le village vote pour éliminer un suspect (vote obligatoire).
        state.phase = Phase.JOUR_VOTE
        votes, fallback_used = day.collect_votes(state, provider, rng=self.rng)
        eliminated = day.resolve_vote(votes)

        if eliminated is not None:
            state.players[eliminated].alive = False
            state.main_room_log.append(
                {"author": None, "text": f"{state.players[eliminated].pseudo} a été éliminé par le vote."}
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
