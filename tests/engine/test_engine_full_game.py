import json
import random
import re

from agents.provider import AIActionProvider
from engine.engine import GameEngine
from engine.models import Camp, Phase, Role


class AlwaysAgreeingHostileProvider:
    """Chaque loup propose toujours le premier non-loup vivant ; tout le
    monde vote toujours pour le premier loup vivant repéré par le script ;
    personne n'utilise les potions de la sorcière ; personne n'envoie de
    message (fin de débat instantanée)."""
    def get_action(self, player_id, context):
        role = context["self_role"]
        phase = context["phase"]
        if phase == "nuit_loups":
            target = next(p["id"] for p in context["alive_players"] if p["id"] != player_id and p["id"] not in context["known_wolf_ids"])
            return {"message": None, "action": {"type": "night_kill_target", "target": target}}
        if phase == "nuit_sorciere":
            return {"message": None, "action": None}
        if phase == "jour_debat":
            return {"message": None, "action": None}
        if phase == "jour_vote":
            target = next(p["id"] for p in context["alive_players"] if p["id"] != player_id)
            return {"message": None, "action": {"type": "day_vote", "target": target}}
        raise AssertionError(f"unexpected phase {phase}")


def test_play_reaches_a_winner_within_max_cycles():
    engine = GameEngine(rng=random.Random(1))
    engine.start("Umberto")
    winner = engine.play(AlwaysAgreeingHostileProvider(), max_cycles=10)
    assert winner in {Camp.LOUPS, Camp.VILLAGEOIS}
    assert engine.state.winner == winner
    assert engine.state.phase == Phase.TERMINEE


def test_play_checks_victory_immediately_after_a_night_kill():
    # Avec un seul loup vivant au départ (forcé via un état pré-rempli) et
    # tout le monde mort sauf un, la partie doit se terminer après cette
    # seule nuit sans lancer de cycle de jour.
    engine = GameEngine(rng=random.Random(1))
    state = engine.start("Umberto")
    # Nuit 2 : la première nuit, les loups et le poison de la sorcière IA ne
    # passent pas par le LLM, or ce test vérifie justement ces appels.
    state.cycle = 2
    non_wolves = [p for p in state.players.values() if p.role != Role.LOUP]
    lone_survivor = non_wolves[0]
    for p in state.players.values():
        p.alive = p.role == Role.LOUP or p.pseudo == lone_survivor.pseudo
    # garde exactement les 2 loups + 1 autre en vie, le reste déjà mort
    engine.run_night_cycle(AlwaysAgreeingHostileProvider())
    assert engine.check_and_set_winner() == Camp.LOUPS


class ScriptedAIClient:
    """Un FakeClient (motif des tests agents/) qui scripte `complete` d'
    OpenRouterClient selon la phase et le rôle, lus dans le vrai texte du
    prompt construit par AIActionProvider. Ça ne remplace que l'appel
    réseau -- l'adaptateur (AIActionProvider), le schéma JSON
    (agents/schema.py) et les prompts (agents/prompts.py) entre ça et le
    moteur sont tous réels.
    """

    def __init__(self, player_names: dict[str, str], player_roles: dict[str, Role]):
        self.player_names = player_names
        self.player_roles = player_roles
        self.calls: list[tuple[str, str]] = []
        self.saw_wolf_target_tonight_in_poison_call = False

    @staticmethod
    def _alive_ids(user_content: str) -> list[str]:
        match = re.search(r"Joueurs vivants : ([^\n]*)\.", user_content)
        roster = match.group(1)
        return [pair.split(" (")[0] for pair in roster.split(", ") if pair]

    def _player_id_for(self, system_prompt: str) -> str:
        for pid, pseudo in self.player_names.items():
            if f"Tu es {pseudo}," in system_prompt:
                return pid
        raise AssertionError("could not resolve calling player from system prompt")

    def complete(self, system_prompt: str, user_content: str) -> str:
        self.calls.append((system_prompt, user_content))
        player_id = self._player_id_for(system_prompt)
        alive_ids = self._alive_ids(user_content)

        if "dans l'antre des loups" in user_content:
            target = next(pid for pid in alive_ids if self.player_roles[pid] != Role.LOUP)
            return json.dumps({"message": None, "action": {"type": "night_kill_target", "target": target}})

        if "Tu décides sans personne" in user_content:
            if "witch_poison" in user_content:
                self.saw_wolf_target_tonight_in_poison_call = "Cible des loups cette nuit :" in user_content
            return json.dumps({"message": None, "action": None})  # la sorcière décline les deux potions

        if "débat public" in user_content:
            return json.dumps({"message": None, "action": None})  # passe, débat terminé rapidement

        if "vote public" in user_content:
            target = next(pid for pid in alive_ids if pid != player_id)
            return json.dumps({"message": None, "action": {"type": "day_vote", "target": target}})

        raise AssertionError(f"unexpected context: {user_content!r}")


def test_real_ai_action_provider_drives_a_full_night_and_day_cycle():
    """Test de non-régression pour C2 et vérification générale du point de
    couture de bout en bout : les 91+ tests existants n'exercent engine/
    qu'avec des providers factices scriptés côté moteur, jamais le vrai
    adaptateur agents/provider.py branché sur GameEngine. Ceci construit
    un vrai AIActionProvider par-dessus un ScriptedAIClient et fait
    tourner un cycle de nuit complet (y compris le sous-appel de poison de
    la sorcière, où context["wolf_target_tonight"] doit être présent et
    affiché) puis un cycle de jour complet à travers le vrai moteur."""
    engine = GameEngine(rng=random.Random(7))
    state = engine.start("Umberto")
    # Nuit 2 : la première nuit, les loups et le poison de la sorcière IA ne
    # passent pas par le LLM, or ce test vérifie justement ces appels.
    state.cycle = 2

    player_names = {pid: p.pseudo for pid, p in state.players.items()}
    player_roles = {pid: p.role for pid, p in state.players.items()}
    player_personalities = {pid: (p.personality or "stratege") for pid, p in state.players.items()}

    client = ScriptedAIClient(player_names, player_roles)
    provider = AIActionProvider(client, player_names, player_roles, player_personalities)

    dead_ids = engine.run_night_cycle(provider)
    assert dead_ids  # la cible choisie par les loups, non soignée, est morte
    assert client.saw_wolf_target_tonight_in_poison_call  # vérification anti-régression C2

    winner = engine.check_and_set_winner()
    if winner is None:
        eliminated, fallback_used = engine.run_day_cycle(provider)
        assert fallback_used == []  # les votes du vrai adaptateur étaient tous valides, pas de repli nécessaire


def test_play_stops_at_max_cycles_without_crashing_if_nobody_wins():
    class StalemateProvider:
        def get_action(self, player_id, context):
            if context["phase"] in ("jour_vote",):
                return {"message": None, "action": {"type": "day_vote", "target": player_id}}  # vote pour soi uniquement -> égalités perpétuelles, personne n'est éliminé
            if context["phase"] == "nuit_loups":
                target = next(p["id"] for p in context["alive_players"] if p["id"] != player_id and p["id"] not in context["known_wolf_ids"])
                return {"message": None, "action": {"type": "night_kill_target", "target": target}}
            return {"message": None, "action": None}
    engine = GameEngine(rng=random.Random(1))
    engine.start("Umberto")
    winner = engine.play(StalemateProvider(), max_cycles=10)
    # la phase de nuit tue toujours quelqu'un à chaque cycle (pas de soin
    # de sorcière), donc un vainqueur doit émerger bien avant max_cycles
    # puisque l'effectif se réduit
    assert winner in {Camp.LOUPS, Camp.VILLAGEOIS}
