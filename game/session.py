"""Partie unique et globale (un seul process, état en mémoire).

Le moteur (`engine.GameEngine`) est synchrone et bloquant : il tourne dans un
thread dédié. Un second thread « observateur » diffuse l'état aux clients
WebSocket dès qu'il change.
"""

from __future__ import annotations

import asyncio
import json
import random
import threading
import time

from channels.layers import get_channel_layer
from django.conf import settings

from engine.engine import GameEngine
from engine.models import Camp, Phase, Role
from game.providers import AIHealth, HumanProvider, RouterProvider, build_ai_provider

GROUP = "game"
ROLE_LABELS = {Role.LOUP: "Loup-Garou", Role.SORCIERE: "Sorcière", Role.VILLAGEOIS: "Villageois"}
PHASE_LABELS = {
    Phase.NUIT_LOUPS: "Nuit — les loups",
    Phase.NUIT_SORCIERE: "Nuit — la sorcière",
    Phase.JOUR_DEBAT: "Jour — débat",
    Phase.JOUR_VOTE: "Jour — vote",
    Phase.TERMINEE: "Partie terminée",
}
WINNER_LABELS = {Camp.LOUPS: "Les Loups-Garous", Camp.VILLAGEOIS: "Le Village"}


class GameSession:
    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.engine: GameEngine | None = None
        self.owner: str | None = None  # clé de session Django du joueur
        self.human: HumanProvider | None = None
        self.thinking: str | None = None
        self.ai_health = AIHealth()
        self._gen = object()  # identifie la partie courante (les anciens threads s'arrêtent)
        self._stop = threading.Event()
        self.running = False
        self.debate_deadline: float | None = None
        self._last_payload = None
        # Boucle asyncio du serveur, enregistrée par les consumers (voir publish).
        self.loop: asyncio.AbstractEventLoop | None = getattr(self, "loop", None)
        # Clients WebSocket connectés ; sans client, la partie est abandonnée après un délai.
        self.clients: int = getattr(self, "clients", 0)
        self._idle_timer: threading.Timer | None = getattr(self, "_idle_timer", None)

    # --- état -------------------------------------------------------------
    @property
    def active(self) -> bool:
        return self.engine is not None and self.engine.state is not None

    @property
    def finished(self) -> bool:
        return self.active and self.engine.state.phase == Phase.TERMINEE

    def is_owner(self, key: str | None) -> bool:
        return self.active and key is not None and key == self.owner

    # --- démarrage / arrêt --------------------------------------------------
    def start(self, owner: str, pseudo: str) -> bool:
        """Lance une partie. False si la partie en cours appartient à quelqu'un d'autre.

        Le propriétaire peut toujours en relancer une : la sienne est alors arrêtée.
        """
        with self._lock:
            if self.active and self.running and not self._stop.is_set() and owner != self.owner:
                return False
            self._stop.set()  # arrête proprement une éventuelle ancienne partie
            old_human = self.human
            if old_human:
                old_human.cancel()
            self.reset()
            self.owner = owner
            gen, stop = self._gen, self._stop
            self.engine = GameEngine(debate_duration_s=settings.DEBATE_DURATION_S, rng=random.Random())
            state = self.engine.start(pseudo)
            self.human = HumanProvider(settings.HUMAN_TIMEOUT_S, on_change=self.publish)
            ai = build_ai_provider(state, fake=settings.FAKE_AI, fake_delay_s=settings.FAKE_AI_DELAY_S,
                                  health=self.ai_health)
            provider = RouterProvider(
                self.engine, ai, self.human, stop,
                on_thinking=lambda name: self._set_thinking(gen, name),
            )
            self.running = True
            threading.Thread(target=self._run, args=(gen, self.engine, provider, stop), daemon=True, name="game-loop").start()
            threading.Thread(target=self._watch, args=(gen,), daemon=True, name="game-watch").start()
        return True

    def _set_thinking(self, gen, name) -> None:
        if gen is self._gen:
            self.thinking = name

    def abandon(self) -> None:
        """Arrête la partie tout de suite. Le thread de jeu peut finir son appel IA en cours,
        mais la partie n'est plus « en cours » (plus de reprise possible, nouvelle partie permise)."""
        self._cancel_idle_timer()
        self._stop.set()
        if self.human:
            self.human.cancel()
        self.running = False
        self.thinking = None

    # --- présence du client -------------------------------------------------
    def client_connected(self) -> None:
        with self._lock:
            self.clients += 1
            self._cancel_idle_timer()

    def client_disconnected(self) -> None:
        """Quand le dernier client part, abandonne la partie après un délai de grâce
        (laisse le temps de recharger la page) pour ne pas consommer de jetons dans le vide."""
        with self._lock:
            self.clients = max(0, self.clients - 1)
            if self.clients or not self.running:
                return
            self._cancel_idle_timer()
            gen = self._gen
            timer = threading.Timer(settings.IDLE_ABANDON_S, self._abandon_if_idle, args=(gen,))
            timer.daemon = True
            self._idle_timer = timer
            timer.start()

    def _cancel_idle_timer(self) -> None:
        if self._idle_timer:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _abandon_if_idle(self, gen) -> None:
        with self._lock:
            if gen is not self._gen or self.clients:
                return
        self.abandon()

    # --- boucle de jeu (thread moteur) --------------------------------------
    @staticmethod
    def _pause(stop) -> None:
        if not stop.is_set():
            stop.wait(settings.PHASE_PAUSE_S)

    def _run(self, gen, engine, provider, stop) -> None:
        def say(text: str) -> None:
            engine.state.main_room_log.append({"author": None, "text": text})

        try:
            say("🌙 La nuit tombe, le village s'endort…")
            self._pause(stop)
            if engine.check_and_set_winner() is None:
                for _ in range(10):
                    if stop.is_set():
                        break
                    engine.run_night_cycle(provider)
                    if engine.check_and_set_winner() is not None:
                        break
                    self._pause(stop)

                    deadline = time.time() + engine.debate_duration_s
                    if gen is self._gen:
                        self.debate_deadline = deadline
                    engine.run_day_cycle(provider, is_time_up=lambda: stop.is_set() or time.time() >= deadline)
                    if gen is self._gen:
                        self.debate_deadline = None
                    if engine.check_and_set_winner() is not None:
                        break
                    engine.state.cycle += 1
                    say("🌙 La nuit tombe, le village s'endort…")
                    self._pause(stop)
        finally:
            if gen is self._gen:
                self.running = False
                self.thinking = None
                self.publish()

    # --- diffusion ----------------------------------------------------------
    def _watch(self, gen) -> None:
        while gen is self._gen and self.running:
            self.publish()
            time.sleep(0.25)

    def publish(self) -> None:
        """Diffuse l'état s'il a changé depuis le dernier envoi."""
        loop = self.loop
        if not self.active or loop is None or loop.is_closed():
            return  # aucun client connecté : il recevra l'état complet à sa connexion
        payload = self.snapshot()
        encoded = json.dumps(payload, sort_keys=True)
        if encoded == self._last_payload:
            return
        self._last_payload = encoded
        # Ce code tourne dans un thread de jeu. La couche de canaux en mémoire n'est
        # pas thread-safe : l'envoi doit s'exécuter dans la boucle des consumers
        # (async_to_sync créerait une autre boucle et le réveil serait perdu).
        layer = get_channel_layer()
        asyncio.run_coroutine_threadsafe(
            layer.group_send(GROUP, {"type": "game.state", "payload": payload}), loop
        )

    def snapshot(self) -> dict:
        if not self.active:
            return {"active": False}
        state = self.engine.state
        me = next(p for p in state.players.values() if p.is_human)
        over = state.phase == Phase.TERMINEE
        names = {pid: p.pseudo for pid, p in state.players.items()}

        def entry(e: dict) -> dict:
            return {"author": names.get(e["author"]) if e["author"] else None,
                    "author_id": e["author"], "text": e["text"]}

        wolf_visible = me.role == Role.LOUP

        players = []
        for p in state.players.values():
            # Un loup connaît déjà ses alliés loups (wolf_mates, wolf_log) :
            # cacher leur rôle dans la liste du village ne protège rien, ça
            # oblige juste à recouper avec l'Antre des loups.
            reveal = over or not p.alive or p.id == me.id or (wolf_visible and p.role == Role.LOUP)
            players.append({
                "id": p.id, "pseudo": p.pseudo, "alive": p.alive, "is_me": p.id == me.id,
                "role": p.role.value if reveal else None,
                "role_label": ROLE_LABELS[p.role] if reveal else None,
            })
        pending = self.human.pending if self.human else None
        winner = state.winner
        return {
            "active": True,
            "phase": state.phase.value,
            "phase_label": PHASE_LABELS[state.phase],
            "is_night": state.phase in (Phase.NUIT_LOUPS, Phase.NUIT_SORCIERE),
            "cycle": state.cycle,
            "winner": winner.value if winner else None,
            "winner_label": WINNER_LABELS[winner] if winner else None,
            "i_won": bool(winner) and winner == (Camp.LOUPS if me.role == Role.LOUP else Camp.VILLAGEOIS),
            "me": {
                "id": me.id, "pseudo": me.pseudo, "alive": me.alive, "role": me.role.value,
                "role_label": ROLE_LABELS[me.role],
                "heal_left": me.role == Role.SORCIERE and not me.witch_heal_used,
                "poison_left": me.role == Role.SORCIERE and not me.witch_poison_used,
            },
            "players": players,
            "main_log": [entry(e) for e in list(state.main_room_log)],
            "wolf_log": [entry(e) for e in list(state.wolf_room_log)] if wolf_visible else None,
            "wolf_mates": [p.pseudo for p in state.wolves() if p.id != me.id] if wolf_visible else None,
            "thinking": self.thinking,
            "ai_down": self.ai_health.down,
            "pending": pending,
            "debate_deadline": self.debate_deadline if state.phase == Phase.JOUR_DEBAT else None,
            "running": self.running,
            "human_timeout": settings.HUMAN_TIMEOUT_S,
        }


session = GameSession()
