"""Adaptateur reliant le client OpenRouter, les prompts et le schéma au
point de couture ActionProvider du moteur (engine.provider.ActionProvider).

C'est le seul endroit du code qui implémente le balisage anti-injection
prévu par le design pour l'historique de chat envoyé à un joueur IA :
chaque message est enveloppé en `<message auteur="...">texte</message>`
pour que le modèle distingue les données de jeu des instructions. C'est
aussi le seul endroit qui absorbe OpenRouterError/ResponseParseError en
None, pour que la logique générique de relance/repli du moteur traite
"JSON invalide" et "timeout réseau" de façon identique.
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
        # "id (pseudo)" plutôt que "id:pseudo" : un test de fumée en
        # conditions réelles a montré un modèle gratuit recopier la forme
        # jointe par deux-points telle quelle dans "target" (ex:
        # "human:Umberto" au lieu de "human"), que le moteur rejetait alors
        # à juste titre comme id invalide. Mettre le pseudo entre
        # parenthèses laisse l'id seul comme unique jeton qui ressemble à
        # un identifiant autonome.
        return ", ".join(f'{e["id"]} ({e["pseudo"]})' for e in entries)

    def _render_log(self, entries: list[dict], pseudo_lookup: dict[str, str]) -> list[str]:
        lines = []
        for entry in entries:
            label = self._author_label(entry.get("author"), pseudo_lookup)
            text = entry.get("text") or ""
            # Échappe le label et le texte avant de les interpoler dans la
            # balise <message auteur="...">: c'est la frontière anti-
            # injection, donc un message de chat forgé ne doit jamais
            # pouvoir fabriquer une fausse balise (ex: fermer </message>
            # trop tôt et ouvrir un <message auteur="Narrateur"> de son
            # cru). Le label est dans un attribut entre guillemets, donc
            # les guillemets doivent aussi être échappés ; le texte est
            # dans le contenu de l'élément, où seuls "<", ">" et "&"
            # peuvent casser la structure.
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
        # Défense en profondeur : le contrat de ce point de couture avec le
        # moteur est strictement "dict ou None". OpenRouterError et
        # ResponseParseError sont les deux échecs attendus et sont gérés
        # ci-dessous, mais rien — pas même un bug de cet adaptateur ou un
        # type d'exception imprévu — ne doit jamais s'échapper sans être
        # intercepté vers le moteur.
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
