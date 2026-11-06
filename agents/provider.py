"""Adaptateur reliant le client OpenRouter, les prompts et le schéma au
point de couture ActionProvider du moteur (engine.provider.ActionProvider).

C'est le seul endroit du code qui implémente le balisage anti-injection
prévu par le design pour l'historique de chat envoyé à un joueur IA :
chaque message est enveloppé en `<message auteur="...">texte</message>`
pour que le modèle distingue les données de jeu des instructions.

Cet adaptateur ne connaît aucune règle du jeu : il met en forme ce que le
moteur lui donne et rien d'autre. C'est le moteur qui décide déjà qui a
le droit de voir quoi (engine/context.py), donc il n'y a ici aucun test
de rôle.
"""

from __future__ import annotations

import html
import re

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
        # Le prompt système d'un joueur ne change jamais de la partie :
        # on l'assemble une fois ici plutôt qu'à chaque appel.
        self._system_prompts: dict[str, str] = {
            player_id: assemble_system_prompt(
                player_names[player_id], player_roles[player_id], player_personalities[player_id]
            )
            for player_id in player_names
        }

    def _pseudo(self, player_id: str, pseudo_lookup: dict[str, str]) -> str:
        return pseudo_lookup.get(player_id, self._player_names.get(player_id, player_id))

    def _format_player(self, player_id: str, pseudo: str) -> str:
        # "id (pseudo)" plutôt que "id:pseudo" : un test de fumée en
        # conditions réelles a montré un modèle gratuit recopier la forme
        # jointe par deux-points telle quelle dans "target" (ex:
        # "human:Umberto" au lieu de "human"), que le moteur rejetait alors
        # à juste titre comme id invalide. Mettre le pseudo entre
        # parenthèses laisse l'id seul comme unique jeton qui ressemble à
        # un identifiant autonome.
        return f"{player_id} ({pseudo})"

    def _format_roster(self, entries: list[dict]) -> str:
        return ", ".join(self._format_player(e["id"], e["pseudo"]) for e in entries)

    def _render_log(self, entries: list[dict], pseudo_lookup: dict[str, str], player_id: str) -> list[str]:
        lines = []
        for entry in entries:
            author_id = entry.get("author")
            label = (
                NARRATEUR_LABEL if author_id is None else self._pseudo(author_id, pseudo_lookup)
            )
            if author_id == player_id:
                # Sans ce repère, un modèle se répétait (re-saluer à chaque tour) ou
                # se perdait au point de se proposer lui-même comme victime.
                label += " (toi)"
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

    def _allies_lines(self, context: dict, pseudo_lookup: dict[str, str]) -> list[str]:
        known_wolf_ids = context.get("known_wolf_ids") or []
        if not known_wolf_ids:
            return []
        allies = ", ".join(
            self._format_player(wid, self._pseudo(wid, pseudo_lookup)) for wid in known_wolf_ids
        )
        return [f"Tes alliés loups : {allies}."]

    def _room_lines(self, context: dict, pseudo_lookup: dict[str, str], player_id: str) -> list[str]:
        """Les salons auxquels ce joueur a accès, chacun sous son propre intitulé."""
        lines: list[str] = []
        for titre, entries in (
            ("[Salon principal]", context.get("main_room_log")),
            ("[Salon loups]", context.get("wolf_room_log")),
        ):
            if entries:
                lines.append(titre)
                lines.extend(self._render_log(entries, pseudo_lookup, player_id))
        return lines

    def _dead_lines(self, context: dict) -> list[str]:
        """Les morts et leur rôle, révélé publiquement à leur mort."""
        dead = context.get("dead_players") or []
        if not dead:
            return []
        labels = {"sorciere": "sorcière"}
        listed = ", ".join(f"{d['pseudo']} ({labels.get(d['role'], d['role'])})" for d in dead)
        return [f"Joueurs morts (rôle révélé) : {listed}."]

    def _wolf_target_lines(self, context: dict, pseudo_lookup: dict[str, str]) -> list[str]:
        """Réservé à la sorcière : qui les loups ont désigné cette nuit."""
        target = context.get("wolf_target_tonight")
        if not target:
            return []
        return [
            f"Cible des loups cette nuit : "
            f"{self._format_player(target, self._pseudo(target, pseudo_lookup))}."
        ]

    def _scene_line(self, context: dict, pseudo_lookup: dict[str, str]) -> str:
        """Décrit en mots la scène du tour : où l'agent parle, qui le lit, ce qu'on attend.

        Sans cette description, un modèle recevait un simple code de phase et
        parlait comme en débat public : il saluait « tout le monde » dans
        l'antre des loups, et inventait des soupçons la première nuit faute de
        savoir que le village ne s'était encore jamais réuni.
        """
        phase = context.get("phase")
        legal = context.get("legal_action_types") or []
        cycle = context.get("cycle", 1)
        village_has_spoken = any(
            entry.get("author") is not None for entry in context.get("main_room_log") or []
        )
        never_met = (
            " Le village ne s'est encore jamais réuni : personne n'a parlé ni voté."
            if not village_has_spoken else ""
        )

        if phase == "nuit_loups":
            allies = [self._pseudo(wid, pseudo_lookup) for wid in context.get("known_wolf_ids") or []]
            if allies:
                readers = " et ".join(allies)
                # Tournure sans accord : le genre du pseudo humain est inconnu.
                return (
                    f"Scène : nuit {cycle}, dans l'antre des loups. Salon privé : personne "
                    f"d'autre que {readers} ne te lit. Mettez-vous d'accord sur la victime de "
                    f"cette nuit (jamais {readers}, jamais toi).{never_met}"
                )
            return (
                f"Scène : nuit {cycle}. Tu es le dernier loup : personne ne te lit, "
                f"choisis seul la victime de cette nuit.{never_met}"
            )
        if phase == "nuit_sorciere":
            question = (
                "Utilises-tu ta potion de soin sur la cible des loups ?"
                if "witch_heal" in legal
                else "Utilises-tu ta potion de poison, et sur qui ?"
            )
            return f"Scène : nuit {cycle}. Tu décides sans personne, aucun joueur ne lit ton message. {question}{never_met}"

        # De jour, un loup a aussi son salon privé sous les yeux : sans ce
        # rappel, un modèle peut en reprendre le contenu dans le chat public.
        wolf_warning = ""
        if context.get("self_role") == Role.LOUP.value:
            wolf_warning = (
                " ATTENTION : ce que tu écris ici est lu par tout le village, "
                "villageois compris. Ne mentionne jamais le salon des loups, ton allié "
                "loup, ni vos discussions ou cibles de la nuit : fais-toi passer pour un villageois."
            )
        if phase == "jour_vote":
            return f"Scène : jour {cycle}, vote public : tout le village verra ton vote. Désigne qui éliminer.{wolf_warning}"
        public = f"Scène : jour {cycle}, débat public sur la place du village : tous les joueurs vivants te lisent. "
        if not self._spoke_today(context):
            # Premier message du jour : il n'existe encore rien à soupçonner. Exiger
            # un soupçon ici faisait inventer des faits (« tes yeux ont brillé »).
            expected = (
                "Le débat s'ouvre : personne n'a encore pris la parole aujourd'hui, et la "
                "nuit personne n'a rien vu. Réagis à ce que le matin a révélé (qui est mort "
                "et son rôle, ou personne), puis lance la discussion : une question à un "
                "joueur, une méthode pour trouver les loups, ou un appel à parler."
            )
        else:
            expected = (
                "Chaque message doit faire avancer la partie : soupçon appuyé sur ce qui "
                "s'est dit ou voté, question précise, défense ou proposition de vote. Si tu "
                "n'as pas encore parlé aujourd'hui, réagis d'abord à ce que le matin a "
                "révélé. Ne salue qu'une fois."
            )
        return public + expected + wolf_warning

    @staticmethod
    def _spoke_today(context: dict) -> bool:
        """Un joueur a-t-il parlé depuis le dernier lever du jour ?"""
        log = context.get("main_room_log") or []
        dawn = max(
            (i for i, e in enumerate(log) if e.get("author") is None and "Le jour se lève" in (e.get("text") or "")),
            default=-1,
        )
        return any(e.get("author") is not None for e in log[dawn + 1:])

    def _instructions_line(self, context: dict, alive_players: list[dict]) -> str:
        legal_action_types = context.get("legal_action_types", [])
        example_id = alive_players[0]["id"] if alive_players else "ia_1"
        example_pseudo = alive_players[0]["pseudo"] if alive_players else "Fatima"
        return (
            f"Actions autorisées : {legal_action_types}. "
            f'IMPORTANT : le champ "target" doit être exactement un identifiant seul, '
            f'par exemple "{example_id}" — jamais "{example_id} ({example_pseudo})", '
            "jamais le pseudo, jamais de parenthèses ni de ponctuation ajoutée. "
            'Dans "message", en revanche, désigne toujours les joueurs par leur pseudo, '
            "jamais par leur identifiant."
        )

    def _build_user_content(self, player_id: str, context: dict) -> str:
        """Met en forme le contexte du moteur en un seul message utilisateur."""
        alive_players = context.get("alive_players", [])
        pseudo_lookup = {player["id"]: player["pseudo"] for player in alive_players}

        lines: list[str] = []
        lines += self._allies_lines(context, pseudo_lookup)
        lines += self._room_lines(context, pseudo_lookup, player_id)
        lines.append(f"Joueurs vivants : {self._format_roster(alive_players)}.")
        lines += self._dead_lines(context)
        lines += self._wolf_target_lines(context, pseudo_lookup)
        lines.append(self._scene_line(context, pseudo_lookup))
        lines.append(self._instructions_line(context, alive_players))

        return "\n".join(lines)

    def _replace_ids_in_message(self, response: dict, context: dict) -> dict:
        """Remplace les identifiants internes par les pseudos dans le message.

        Même avec la consigne, un modèle gratuit recopie parfois "ia_1" dans
        son message : l'identifiant ne doit jamais atteindre le chat. Le
        champ "target" n'est pas touché, le moteur attend bien l'id.
        """
        message = response.get("message")
        if not message:
            return response
        for player in context.get("alive_players", []):
            message = re.sub(rf"\b{re.escape(player['id'])}\b", player["pseudo"], message)
        return {**response, "message": message}

    def get_action(self, player_id: str, context: dict) -> dict | None:
        try:
            system_prompt = self._system_prompts[player_id]
            user_content = self._build_user_content(player_id, context)
            response = parse_response(self._client.complete(system_prompt, user_content))
            return self._replace_ids_in_message(response, context)
        except (OpenRouterError, ResponseParseError):
            # Les deux échecs attendus : l'API n'a rien rendu d'exploitable,
            # ou le modèle n'a pas respecté le contrat JSON.
            return None
        except Exception:
            # Défense en profondeur : le contrat de ce point de couture avec
            # le moteur est strictement "dict ou None". Rien, pas même un
            # bug de cet adaptateur, ne doit faire planter un tour de jeu.
            return None
