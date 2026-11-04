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

import html

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

    def _format_roster(self, entries: list[dict]) -> str:
        # "id (pseudo)" rather than "id:pseudo": a live-model smoke test
        # showed a free model copying the colon-joined form verbatim into
        # "target" (e.g. "human:Umberto" instead of "human"), which the
        # engine then correctly rejected as an invalid id. Parenthesizing
        # the pseudo keeps the bare id as the only token that looks like a
        # standalone identifier.
        return ", ".join(f'{e["id"]} ({e["pseudo"]})' for e in entries)

    def _render_log(self, entries: list[dict], pseudo_lookup: dict[str, str]) -> list[str]:
        lines = []
        for entry in entries:
            label = self._author_label(entry.get("author"), pseudo_lookup)
            text = entry.get("text") or ""
            # Escape both the label and the text before interpolating them
            # into the <message auteur="..."> tag: this is the anti-prompt-
            # injection boundary, so a crafted chat message must never be
            # able to forge a fake tag (e.g. by closing </message> early and
            # opening a new <message auteur="Narrateur"> of its own). The
            # label sits inside a quoted attribute, so it also needs quotes
            # escaped; the text sits inside element content, where only
            # "<", ">" and "&" can break the structure.
            escaped_label = html.escape(label, quote=True)
            escaped_text = html.escape(text, quote=False)
            lines.append(f'<message auteur="{escaped_label}">{escaped_text}</message>')
        return lines

    def _build_user_content(self, player_id: str, context: dict) -> str:
        pseudo_lookup = {
            player["id"]: player["pseudo"] for player in context.get("alive_players", [])
        }

        def resolve(pid: str) -> str:
            return pseudo_lookup.get(pid, self._player_names.get(pid, pid))

        lines: list[str] = []

        known_wolf_ids = context.get("known_wolf_ids") or []
        if known_wolf_ids:
            allies = self._format_roster([{"id": wid, "pseudo": resolve(wid)} for wid in known_wolf_ids])
            lines.append(f"Tes alliés loups : {allies}.")

        main_room_log = context.get("main_room_log") or []
        if main_room_log:
            lines.append("[Salon principal]")
            lines.extend(self._render_log(main_room_log, pseudo_lookup))

        wolf_room_log = context.get("wolf_room_log")
        if wolf_room_log and self._player_roles.get(player_id) == Role.LOUP:
            lines.append("[Salon loups]")
            lines.extend(self._render_log(wolf_room_log, pseudo_lookup))

        alive_players = context.get("alive_players", [])
        lines.append(f"Joueurs vivants : {self._format_roster(alive_players)}.")

        wolf_target_tonight = context.get("wolf_target_tonight")
        if wolf_target_tonight:
            target_entry = [{"id": wolf_target_tonight, "pseudo": resolve(wolf_target_tonight)}]
            lines.append(f"Cible des loups cette nuit : {self._format_roster(target_entry)}.")

        phase = context.get("phase")
        legal_action_types = context.get("legal_action_types", [])
        example_id = alive_players[0]["id"] if alive_players else "ia_1"
        example_pseudo = alive_players[0]["pseudo"] if alive_players else "Fatima"
        lines.append(
            f"Phase actuelle : {phase}. Actions autorisées : {legal_action_types}. "
            f'IMPORTANT : le champ "target" doit être exactement un identifiant seul, '
            f'par exemple "{example_id}" — jamais "{example_id} ({example_pseudo})", '
            "jamais le pseudo, jamais de parenthèses ni de ponctuation ajoutée."
        )

        return "\n".join(lines)

    def get_action(self, player_id: str, context: dict) -> dict | None:
        # Defense in depth: this seam's contract with the engine is strictly
        # "dict or None". OpenRouterError/ResponseParseError are the two
        # expected failure modes and are handled below, but nothing — not
        # even a bug in this adapter or an exception type nobody
        # anticipated — may ever escape uncaught into the engine.
        try:
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
        except Exception:
            return None
