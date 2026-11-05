"""Suivi du coût en jetons (tokens) par manche de jeu.

Une manche = un cycle du moteur (nuit + jour, `GameState.cycle`). Chaque appel
LLM réussi rapporte son `usage` (renvoyé par l'API façon OpenAI) ; on cumule
les jetons dans la manche en cours et on réécrit le fichier JSON de la partie
à chaque appel, pour qu'une partie abandonnée garde quand même ses chiffres.

Un fichier par partie : cost_efficiency/<game_id>.json
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "cost_efficiency"
TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")


def _to_int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


class RoundCostTracker:
    """Cumule les jetons consommés par manche et les enregistre en JSON."""

    def __init__(
        self,
        get_round: Callable[[], int],
        directory: Path | str = DEFAULT_DIR,
        game_id: str | None = None,
    ):
        self._get_round = get_round
        self.started_at = datetime.now(timezone.utc)
        self.game_id = game_id or f"{self.started_at:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
        self.path = Path(directory) / f"{self.game_id}.json"
        self._rounds: dict[int, dict[str, int]] = {}
        self._lock = threading.Lock()

    def record(self, usage: dict | None) -> None:
        """Ajoute l'`usage` d'un appel LLM à la manche en cours, puis sauvegarde."""
        if not isinstance(usage, dict):
            return
        prompt = _to_int(usage.get("prompt_tokens"))
        completion = _to_int(usage.get("completion_tokens"))
        total = _to_int(usage.get("total_tokens")) or prompt + completion
        with self._lock:
            entry = self._rounds.setdefault(
                self._get_round(), {"calls": 0, **{f: 0 for f in TOKEN_FIELDS}}
            )
            entry["calls"] += 1
            entry["prompt_tokens"] += prompt
            entry["completion_tokens"] += completion
            entry["total_tokens"] += total
            self._save()

    def report(self) -> dict:
        rounds = [{"round": r, **self._rounds[r]} for r in sorted(self._rounds)]
        return {
            "game_id": self.game_id,
            "started_at": self.started_at.isoformat(),
            "rounds": rounds,
            "total": {f: sum(r[f] for r in rounds) for f in ("calls", *TOKEN_FIELDS)},
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.report(), indent=2), encoding="utf-8")
        tmp.replace(self.path)
