"""Première nuit : personne ne sait rien, donc le moteur n'appelle pas le LLM.

Interroger un modèle sans aucune information le poussait à inventer des
faits (« Sarah a trop parlé », « elle a l'air timide »). Le moteur tire donc
au sort à sa place ; seul l'humain est encore consulté.
"""

import random

from engine.models import GameState, Phase, Player, Role
from engine.night import resolve_wolf_phase, resolve_witch_phase


def _state(*, human_role: Role | None, cycle: int = 1) -> GameState:
    roles = [Role.LOUP, Role.LOUP, Role.SORCIERE, Role.VILLAGEOIS, Role.VILLAGEOIS]
    players = {}
    if human_role is not None:
        roles.remove(human_role)
        players["human"] = Player(id="human", pseudo="Capucine", is_human=True, role=human_role, personality=None)
    for i, role in enumerate(roles, start=1):
        players[f"ia_{i}"] = Player(id=f"ia_{i}", pseudo=f"P{i}", is_human=False, role=role, personality="stratege")
    return GameState(players=players, phase=Phase.NUIT_LOUPS, cycle=cycle)


class RecordingProvider:
    """Répond pour l'humain selon un script ; échoue si une IA est interrogée."""

    def __init__(self, human_replies=None):
        self.human_replies = list(human_replies or [])
        self.asked = []

    def get_action(self, player_id, context):
        self.asked.append(player_id)
        assert player_id == "human", f"le LLM ne doit pas être appelé pour {player_id} la première nuit"
        return self.human_replies.pop(0) if self.human_replies else None


def kill(target):
    return {"message": None, "action": {"type": "night_kill_target", "target": target}}


def _non_wolves(state):
    return {p.id for p in state.players.values() if p.role != Role.LOUP}


def test_two_ai_wolves_get_a_random_victim_without_any_llm_call():
    state = _state(human_role=Role.VILLAGEOIS)
    provider = RecordingProvider()
    target = resolve_wolf_phase(state, provider, rng=random.Random(3))
    assert provider.asked == []
    assert target in _non_wolves(state)
    # Les loups IA retrouveront ce repère dans leur antre la nuit suivante.
    assert any("le sort désigne" in e["text"] for e in state.wolf_room_log if e["author"] is None)


def test_the_ai_ally_rallies_to_the_human_wolfs_proposal():
    state = _state(human_role=Role.LOUP)
    victim = next(iter(_non_wolves(state)))
    provider = RecordingProvider([kill(victim)])
    assert resolve_wolf_phase(state, provider, rng=random.Random(3)) == victim
    assert provider.asked == ["human"]
    ally = next(p for p in state.wolves() if not p.is_human)
    assert {"author": ally.id, "text": f"D'accord pour {state.players[victim].pseudo}."} in state.wolf_room_log


def test_the_ai_ally_proposes_at_random_when_the_human_wolf_hesitates():
    state = _state(human_role=Role.LOUP)
    provider = RecordingProvider([{"message": "Je ne sais pas", "action": None}] * 3)
    target = resolve_wolf_phase(state, provider, rng=random.Random(3))
    ally = next(p for p in state.wolves() if not p.is_human)
    said = [e["text"] for e in state.wolf_room_log if e["author"] == ally.id]
    # Une seule phrase franche, sans fait inventé, puis il ne se répète pas.
    assert said == [f"Première nuit, on ne sait rien de personne : je propose {state.players[target].pseudo}, au hasard."]
    assert target in _non_wolves(state)


def test_the_ai_ally_follows_the_human_who_changes_their_mind_in_round_two():
    state = _state(human_role=Role.LOUP)
    victim = sorted(_non_wolves(state))[-1]
    provider = RecordingProvider([{"message": "Je ne sais pas", "action": None}, kill(victim)])
    assert resolve_wolf_phase(state, provider, rng=random.Random(3)) == victim


def test_from_the_second_night_ai_wolves_are_asked_again():
    state = _state(human_role=Role.VILLAGEOIS, cycle=2)
    victim = next(iter(_non_wolves(state)))

    class Agreeing:
        asked = []

        def get_action(self, player_id, context):
            self.asked.append(player_id)
            return kill(victim)

    provider = Agreeing()
    assert resolve_wolf_phase(state, provider, rng=random.Random(3)) == victim
    assert len(provider.asked) == 2


def test_the_ai_witch_is_not_asked_to_poison_on_the_first_night_but_still_to_heal():
    state = _state(human_role=Role.VILLAGEOIS)
    witch = next(p for p in state.players.values() if p.role == Role.SORCIERE)
    victim = next(p.id for p in state.players.values() if p.role == Role.VILLAGEOIS and not p.is_human)

    class Witch:
        asked = []

        def get_action(self, player_id, context):
            self.asked.append(context["legal_action_types"])
            return None

    provider = Witch()
    assert resolve_witch_phase(state, provider, victim) == (False, None)
    assert provider.asked == [["witch_heal"]]
    assert not witch.witch_poison_used


def test_a_human_witch_keeps_her_poison_choice_on_the_first_night():
    state = _state(human_role=Role.SORCIERE)
    victim = next(p.id for p in state.players.values() if p.role == Role.VILLAGEOIS)

    class Witch:
        asked = []

        def get_action(self, player_id, context):
            self.asked.append(context["legal_action_types"])
            return None

    provider = Witch()
    resolve_witch_phase(state, provider, victim)
    assert provider.asked == [["witch_heal"], ["witch_poison"]]
