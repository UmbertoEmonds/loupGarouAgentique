from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Role(str, Enum):
    LOUP = "loup"
    SORCIERE = "sorciere"
    VILLAGEOIS = "villageois"


class Camp(Enum):
    LOUPS = "loups"
    VILLAGEOIS = "villageois"


class Phase(Enum):
    NUIT_LOUPS = "nuit_loups"
    NUIT_SORCIERE = "nuit_sorciere"
    JOUR_DEBAT = "jour_debat"
    JOUR_VOTE = "jour_vote"
    TERMINEE = "terminee"


class ActionType(Enum):
    NIGHT_KILL_TARGET = "night_kill_target"
    WITCH_HEAL = "witch_heal"
    WITCH_POISON = "witch_poison"
    DAY_VOTE = "day_vote"


ROLE_TO_CAMP: dict[Role, Camp] = {
    Role.LOUP: Camp.LOUPS,
    Role.SORCIERE: Camp.VILLAGEOIS,
    Role.VILLAGEOIS: Camp.VILLAGEOIS,
}


@dataclass
class Player:
    id: str
    pseudo: str
    is_human: bool
    role: Role
    personality: str | None
    alive: bool = True
    witch_heal_used: bool = False
    witch_poison_used: bool = False


@dataclass
class GameState:
    players: dict[str, Player]
    phase: Phase
    cycle: int
    main_room_log: list[dict] = field(default_factory=list)
    wolf_room_log: list[dict] = field(default_factory=list)
    last_wolf_target: str | None = None
    winner: Camp | None = None

    def alive_ids(self) -> list[str]:
        return [pid for pid, p in self.players.items() if p.alive]

    def wolves(self) -> list[Player]:
        return [p for p in self.players.values() if p.role == Role.LOUP]

    def get(self, player_id: str) -> Player:
        return self.players[player_id]
