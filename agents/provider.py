"""Adapter wiring the OpenRouter client, prompts, and schema into the
engine's ActionProvider seam (engine.provider.ActionProvider).

This is the only place in the codebase that implements the spec's
anti-prompt-injection tagging of chat history sent to an AI player:
each message is wrapped as `<message auteur="...">texte</message>` so
the model can distinguish game data from instructions. It's also the
only place that swallows OpenRouterError/ResponseParseError into None,
letting the engine's generic retry/fallback logic treat "bad JSON" and
"network timeout" identically.
"""

from __future__ import annotations

from agents.client import OpenRouterClient, OpenRouterError
from agents.prompts import assemble_system_prompt
from agents.schema import ResponseParseError, parse_response
from engine.models import Role

NARRATEUR_LABEL = "Narrateur"


class AIActionProvider:
    def __init__(
        self,
        client: OpenRouterClient,
        player_names: dict[str, str],
        player_roles: dict[str, Role],
        player_personalities: dict[str, str],
    ):
        self._client = client
        self._player_names = player_names
        self._player_roles = player_roles
        self._system_prompts: dict[str, str] = {
            player_id: assemble_system_prompt(
                player_names[player_id], player_roles[player_id], player_personalities[player_id]
            )
            for player_id in player_names
        }

    def _author_label(self, author_id: str | None, pseudo_lookup: dict[str, str]) -> str:
        if author_id is None:
            return NARRATEUR_LABEL
        return pseudo_lookup.get(author_id, self._player_names.get(author_id, author_id))

    def _render_log(self, entries: list[dict], pseudo_lookup: dict[str, str]) -> list[str]:
        return [
            f'<message auteur="{self._author_label(entry.get("author"), pseudo_lookup)}">{entry["text"]}</message>'
            for entry in entries
        ]

    def _build_user_content(self, player_id: str, context: dict) -> str:
        pseudo_lookup = {
            player["id"]: player["pseudo"] for player in context.get("alive_players", [])
        }

        lines = self._render_log(context.get("main_room_log", []), pseudo_lookup)

        wolf_room_log = context.get("wolf_room_log")
        if wolf_room_log is not None and self._player_roles.get(player_id) == Role.LOUP:
            lines.extend(self._render_log(wolf_room_log, pseudo_lookup))

        phase = context.get("phase")
        legal_action_types = context.get("legal_action_types", [])
        lines.append(f"Phase actuelle : {phase}. Actions autorisées : {legal_action_types}.")

        return "\n".join(lines)

    def get_action(self, player_id: str, context: dict) -> dict | None:
        system_prompt = self._system_prompts[player_id]
        user_content = self._build_user_content(player_id, context)

        try:
            raw_text = self._client.complete(system_prompt, user_content)
        except OpenRouterError:
            return None

        try:
            return parse_response(raw_text)
        except ResponseParseError:
            return None
