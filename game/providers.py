"""Implémentations de `engine.provider.ActionProvider` côté front.

- HumanProvider   : bloque le thread moteur jusqu'à ce que l'humain réponde
                    (via WebSocket) ou que son délai expire (-> None = repli).
- FakeAIProvider  : IA scriptée locale (FAKE_AI=1) pour tester sans clé API.
- RouterProvider  : aiguille chaque appel du moteur vers l'humain ou l'IA.
"""

from __future__ import annotations

import random
import threading
import time
import uuid

MAX_MESSAGE_LEN = 500


class HumanProvider:
    def __init__(self, timeout_s: float, on_change=None):
        self.timeout_s = timeout_s
        self._on_change = on_change or (lambda: None)
        self._cond = threading.Condition()
        self._pending: dict | None = None
        self._response: dict | None = None
        self._answered = False
        self._expired: set[tuple] = set()
        self._cancelled = False

    # --- côté moteur (thread de jeu) -------------------------------------
    def ask(self, key: tuple, pending: dict) -> dict | None:
        """Publie une demande et attend la réponse. None si délai dépassé."""
        with self._cond:
            if self._cancelled or key in self._expired:
                return None
            pending = {
                **pending,
                "id": uuid.uuid4().hex,
                "deadline": time.time() + self.timeout_s,
            }
            self._pending = pending
            self._response, self._answered = None, False
        self._on_change()

        with self._cond:
            self._cond.wait_for(lambda: self._answered or self._cancelled, timeout=self.timeout_s)
            answered = self._answered
            response = self._response if answered else None
            if not answered and not self._cancelled:
                # Une fois le délai dépassé, on ne rattend pas pour cette phase
                # (évite 2 x 75 s lors des tentatives répétées du vote).
                self._expired.add(key)
            self._pending = None
        self._on_change()
        return response

    def cancel(self) -> None:
        with self._cond:
            self._cancelled = True
            self._cond.notify_all()

    # --- côté WebSocket (thread asyncio) ----------------------------------
    @property
    def pending(self) -> dict | None:
        return self._pending

    def submit(self, request_id: str, payload: dict) -> str | None:
        """Valide la réponse du client. Retourne un message d'erreur, ou None si OK."""
        with self._cond:
            pending = self._pending
            if pending is None or pending["id"] != request_id or self._answered:
                return "Cette demande n'est plus d'actualité."
            response, error = build_response(pending, payload)
            if error:
                return error
            self._response, self._answered = response, True
            self._cond.notify_all()
        return None


def _clean_message(payload: dict) -> str | None:
    text = payload.get("message")
    if not isinstance(text, str):
        return None
    text = " ".join(text.split())[:MAX_MESSAGE_LEN]
    return text or None


def build_response(pending: dict, payload: dict) -> tuple[dict | None, str | None]:
    """Transforme la saisie du client en réponse au format du contrat d'agent.

    Le moteur re-valide de toute façon (« l'IA propose, le moteur valide »),
    mais on refuse tôt une cible hors liste pour pouvoir réafficher le formulaire.
    """
    kind = pending["kind"]
    message = _clean_message(payload) if pending.get("allow_message") else None
    target = payload.get("target")
    allowed = {t["id"] for t in pending.get("targets", [])}

    if kind == "debate":
        return {"message": message, "action": None}, None

    if kind == "witch_heal":
        if payload.get("accept"):
            if not pending.get("can_accept"):
                return None, "Tu ne peux pas te soigner toi-même."
            return {"message": None, "action": {"type": "witch_heal", "target": pending["victim_id"]}}, None
        return {"message": None, "action": None}, None

    if kind == "witch_poison" and not payload.get("accept"):
        return {"message": None, "action": None}, None

    if target not in allowed:
        return None, "Choisis une cible dans la liste."
    action_type = {"wolf_kill": "night_kill_target", "witch_poison": "witch_poison", "vote": "day_vote"}[kind]
    return {"message": message, "action": {"type": action_type, "target": target}}, None


# ---------------------------------------------------------------------------

_FAKE_LINES = [
    "Je trouve certains comportements bien étranges…",
    "Quelqu'un a quelque chose à se reprocher ici.",
    "Je n'ai pas encore d'avis tranché, mais je surveille.",
    "On devrait écouter ceux qui parlent le moins.",
    "Je vote pour la prudence, ne précipitons rien.",
]


class FakeAIProvider:
    """IA scriptée : réponses plausibles et valides, sans réseau."""

    def __init__(self, rng: random.Random | None = None, delay_s: float = 0.4):
        self.rng = rng or random.Random()
        self.delay_s = delay_s

    def get_action(self, player_id: str, context: dict) -> dict | None:
        time.sleep(self.delay_s)
        others = [p["id"] for p in context["alive_players"] if p["id"] != player_id]
        legal = context.get("legal_action_types") or []
        phase = context["phase"]
        if phase == "nuit_loups":
            wolves = set(context.get("known_wolf_ids") or []) | {player_id}
            targets = [p for p in others if p not in wolves]
            return {"message": "On prend celui-là ?", "action": {"type": "night_kill_target", "target": self.rng.choice(targets)}}
        if "witch_heal" in legal:
            victim = context.get("wolf_target_tonight")
            if victim and victim != player_id and self.rng.random() < 0.5:
                return {"message": None, "action": {"type": "witch_heal", "target": victim}}
            return {"message": None, "action": None}
        if "witch_poison" in legal:
            return {"message": None, "action": None}
        if "day_vote" in legal:
            return {"message": None, "action": {"type": "day_vote", "target": self.rng.choice(others)}}
        message = self.rng.choice(_FAKE_LINES) if self.rng.random() < 0.7 else None
        return {"message": message, "action": None}


class RouterProvider:
    """Aiguille les appels du moteur : joueur humain -> HumanProvider, sinon IA."""

    def __init__(self, engine, ai_provider, human: HumanProvider, stop: threading.Event, on_thinking=None):
        self.engine = engine
        self.ai = ai_provider
        self.human = human
        self.stop = stop
        self.on_thinking = on_thinking or (lambda name: None)

    def get_action(self, player_id: str, context: dict) -> dict | None:
        # Partie abandonnée : on répond None tout de suite, le moteur applique ses replis.
        if self.stop.is_set():
            return None
        state = self.engine.state
        player = state.get(player_id)
        if not player.is_human:
            self.on_thinking(player.pseudo)
            try:
                return self.ai.get_action(player_id, context)
            finally:
                self.on_thinking(None)

        pending = describe_request(state, player, context)
        key = (state.cycle, context["phase"], tuple(context.get("legal_action_types") or []))
        return self.human.ask(key, pending)


def describe_request(state, player, context: dict) -> dict:
    """Décrit ce qu'on demande à l'humain, pour que l'interface affiche le bon formulaire."""
    phase = context["phase"]
    legal = context.get("legal_action_types") or []
    alive = context["alive_players"]
    others = [p for p in alive if p["id"] != player.id]

    if phase == "nuit_loups":
        mates = set(context.get("known_wolf_ids") or [])
        return {
            "kind": "wolf_kill", "allow_message": True,
            "prompt": "Les loups se réveillent. Concertez-vous et choisissez une victime.",
            "targets": [p for p in others if p["id"] not in mates],
        }
    if "witch_heal" in legal:
        victim_id = context.get("wolf_target_tonight")
        victim = next((p for p in alive if p["id"] == victim_id), None)
        return {
            "kind": "witch_heal", "allow_message": False,
            "prompt": f"{victim['pseudo'] if victim else '?'} a été attaqué par les loups. Utiliser ta potion de vie ?",
            "victim_id": victim_id, "targets": [],
            # Une sorcière ne peut pas se soigner elle-même (règle du moteur).
            "can_accept": victim_id is not None and victim_id != player.id,
        }
    if "witch_poison" in legal:
        return {
            "kind": "witch_poison", "allow_message": False,
            "prompt": "Veux-tu empoisonner quelqu'un cette nuit ?", "targets": others,
        }
    if "day_vote" in legal:
        return {
            "kind": "vote", "allow_message": False,
            "prompt": "Le village doit voter. Qui éliminer ?", "targets": others,
        }
    return {
        "kind": "debate", "allow_message": True,
        "prompt": "C'est ton tour de parler au village.", "targets": [],
    }


def build_ai_provider(state, fake: bool, fake_delay_s: float = 0.4):
    """IA réelle (OpenRouter) ou scriptée, selon la configuration."""
    if fake:
        return FakeAIProvider(delay_s=fake_delay_s)
    from agents.client import OpenRouterClient
    from agents.provider import AIActionProvider

    ia = {pid: p for pid, p in state.players.items() if not p.is_human}
    provider = AIActionProvider(
        OpenRouterClient(),
        {pid: p.pseudo for pid, p in ia.items()},
        {pid: p.role for pid, p in ia.items()},
        {pid: p.personality for pid, p in ia.items()},
    )
    # Le pseudo de l'humain doit rester lisible dans l'historique envoyé aux IA,
    # même une fois l'humain mort (il n'a pas de prompt système, donc pas dans `ia`).
    human = next(p for p in state.players.values() if p.is_human)
    provider._player_names["human"] = human.pseudo
    return provider
