from engine.models import GameState, Phase, Player, Role
from engine.night import apply_night_deaths, resolve_witch_phase


def make_state_with_witch(witch: str, others: list[str]) -> GameState:
    players = {witch: Player(id=witch, pseudo=witch, is_human=False, role=Role.SORCIERE, personality=None)}
    for pid in others:
        players[pid] = Player(id=pid, pseudo=pid, is_human=False, role=Role.VILLAGEOIS, personality=None)
    return GameState(players=players, phase=Phase.NUIT_SORCIERE, cycle=1)


class ScriptedProvider:
    def __init__(self, scripts: dict[str, list[dict | None]]):
        self.scripts = scripts

    def get_action(self, player_id, context):
        return self.scripts[player_id].pop(0)


def heal(target):
    return {"message": None, "action": {"type": "witch_heal", "target": target}}


def poison(target):
    return {"message": None, "action": {"type": "witch_poison", "target": target}}


def decline():
    return {"message": None, "action": None}


def test_witch_heals_the_wolves_victim():
    state = make_state_with_witch("ia_1", others=["ia_2"])
    provider = ScriptedProvider({"ia_1": [heal("ia_2"), decline()]})
    healed, poisoned = resolve_witch_phase(state, provider, wolf_target="ia_2")
    assert (healed, poisoned) == (True, None)
    assert state.get("ia_1").witch_heal_used is True


def test_witch_cannot_heal_herself_even_if_targeted():
    state = make_state_with_witch("ia_1", others=["ia_2"])
    provider = ScriptedProvider({"ia_1": [heal("ia_1"), decline()]})
    healed, poisoned = resolve_witch_phase(state, provider, wolf_target="ia_1")
    assert healed is False  # invalid self-heal rejected, treated as declined


def test_witch_heals_and_poisons_in_the_same_night_independently():
    state = make_state_with_witch("ia_1", others=["ia_2", "ia_3"])
    provider = ScriptedProvider({"ia_1": [heal("ia_2"), poison("ia_3")]})
    healed, poisoned = resolve_witch_phase(state, provider, wolf_target="ia_2")
    assert (healed, poisoned) == (True, "ia_3")
    assert state.get("ia_1").witch_heal_used is True
    assert state.get("ia_1").witch_poison_used is True


def test_a_mismatched_action_type_during_the_poison_sub_call_does_not_poison_anyone():
    # La réponse de l'agent annonce action.type "witch_heal" pendant le
    # sous-appel de poison. Même si la cible serait une victime de poison
    # légale, le type annoncé ne correspond pas à ce que le moteur demande
    # en ce moment, donc ça doit être traité exactement comme "aucune
    # soumission valide" plutôt que réinterprété silencieusement en poison.
    state = make_state_with_witch("ia_1", others=["ia_2", "ia_3"])
    mismatched_poison = {"message": None, "action": {"type": "witch_heal", "target": "ia_3"}}
    provider = ScriptedProvider({"ia_1": [decline(), mismatched_poison]})
    healed, poisoned = resolve_witch_phase(state, provider, wolf_target="ia_2")
    assert poisoned is None
    assert state.get("ia_1").witch_poison_used is False


def test_a_mismatched_action_type_during_the_heal_sub_call_does_not_heal_anyone():
    state = make_state_with_witch("ia_1", others=["ia_2"])
    mismatched_heal = {"message": None, "action": {"type": "witch_poison", "target": "ia_2"}}
    provider = ScriptedProvider({"ia_1": [mismatched_heal, decline()]})
    healed, poisoned = resolve_witch_phase(state, provider, wolf_target="ia_2")
    assert healed is False
    assert state.get("ia_1").witch_heal_used is False


def test_witch_may_poison_herself():
    state = make_state_with_witch("ia_1", others=["ia_2"])
    provider = ScriptedProvider({"ia_1": [decline(), poison("ia_1")]})
    healed, poisoned = resolve_witch_phase(state, provider, wolf_target="ia_2")
    assert poisoned == "ia_1"


def test_witch_cannot_reuse_a_potion_already_used_in_a_previous_cycle():
    state = make_state_with_witch("ia_1", others=["ia_2", "ia_3"])
    state.get("ia_1").witch_heal_used = True
    state.get("ia_1").witch_poison_used = True
    provider = ScriptedProvider({})  # ne doit jamais être appelé pour une sorcière épuisée
    healed, poisoned = resolve_witch_phase(state, provider, wolf_target="ia_2")
    assert (healed, poisoned) == (False, None)


def test_apply_night_deaths_applies_unhealed_wolf_kill():
    state = make_state_with_witch("ia_1", others=["ia_2"])
    dead = apply_night_deaths(state, wolf_target="ia_2", healed=False, poisoned_id=None)
    assert dead == ["ia_2"]
    assert state.get("ia_2").alive is False


def test_apply_night_deaths_healed_wolf_kill_produces_no_wolf_death():
    state = make_state_with_witch("ia_1", others=["ia_2"])
    dead = apply_night_deaths(state, wolf_target="ia_2", healed=True, poisoned_id=None)
    assert dead == []
    assert state.get("ia_2").alive is True


def test_apply_night_deaths_poison_and_wolf_kill_both_apply():
    state = make_state_with_witch("ia_1", others=["ia_2", "ia_3"])
    dead = apply_night_deaths(state, wolf_target="ia_2", healed=False, poisoned_id="ia_3")
    assert sorted(dead) == ["ia_2", "ia_3"]


def test_witch_poisoning_a_wolf_does_not_double_count_if_already_the_wolf_target():
    state = make_state_with_witch("ia_1", others=["ia_2"])
    dead = apply_night_deaths(state, wolf_target="ia_2", healed=False, poisoned_id="ia_2")
    assert dead == ["ia_2"]
