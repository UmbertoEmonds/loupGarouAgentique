"""Suivi du coût en jetons (tokens) par manche de jeu, enregistré en base.

Une manche = un cycle du moteur (nuit + jour, `GameState.cycle`). Chaque appel
LLM réussi rapporte son `usage` (renvoyé par l'API façon OpenAI) ; on ajoute
ses jetons à la ligne `RoundCost` de la manche en cours. L'écriture a lieu à
chaque appel, pour qu'une partie abandonnée garde quand même ses chiffres.

La ligne `Game` n'est créée qu'au premier usage reçu : une partie sans aucun
appel LLM (IA scriptée, abandon immédiat) ne laisse rien en base.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Callable

from django.db import close_old_connections, transaction
from django.db.models import F
from django.utils import timezone

from monitoring.models import Game, RoundCost

logger = logging.getLogger(__name__)
TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")


def _to_int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


class RoundCostTracker:
    """Cumule en base les jetons consommés par manche d'une partie."""

    def __init__(self, get_round: Callable[[], int], game_id: str | None = None):
        self._get_round = get_round
        self.started_at = timezone.now()
        self.game_id = game_id or f"{self.started_at:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
        self._game: Game | None = None
        self._lock = threading.Lock()

    def record(self, usage: dict | None) -> None:
        """Ajoute l'`usage` d'un appel LLM à la manche en cours."""
        if not isinstance(usage, dict):
            return
        prompt = _to_int(usage.get("prompt_tokens"))
        completion = _to_int(usage.get("completion_tokens"))
        total = _to_int(usage.get("total_tokens")) or prompt + completion
        with self._lock:
            try:
                self._add(self._get_round(), prompt, completion, total)
            except Exception:
                # Base injoignable, etc. : on perd ce point de mesure, pas la partie.
                logger.exception("Échec de l'enregistrement du coût en jetons (partie %s)", self.game_id)

    def _add(self, round_number: int, prompt: int, completion: int, total: int) -> None:
        # Appelé depuis le thread de jeu, hors du cycle requête/réponse de Django :
        # c'est donc à nous de recycler une connexion trop vieille ou cassée.
        close_old_connections()
        with transaction.atomic():
            if self._game is None:
                self._game, _ = Game.objects.get_or_create(
                    game_id=self.game_id, defaults={"started_at": self.started_at}
                )
            row, _ = RoundCost.objects.get_or_create(game=self._game, round=round_number)
            RoundCost.objects.filter(pk=row.pk).update(
                calls=F("calls") + 1,
                prompt_tokens=F("prompt_tokens") + prompt,
                completion_tokens=F("completion_tokens") + completion,
                total_tokens=F("total_tokens") + total,
            )

    def report(self) -> dict:
        """Résumé de la partie : jetons par manche et total."""
        rounds = list(
            RoundCost.objects.filter(game__game_id=self.game_id)
            .order_by("round")
            .values("round", "calls", *TOKEN_FIELDS)
        )
        return {
            "game_id": self.game_id,
            "started_at": self.started_at.isoformat(),
            "rounds": rounds,
            "total": {f: sum(r[f] for r in rounds) for f in ("calls", *TOKEN_FIELDS)},
        }
