import random

from engine.models import GameState, Phase, Player, Role
from engine.night import resolve_wolf_phase


def make_state_with_wolves(*wolves: str, others: list[str]) -> GameState:
    players = {}
    for pid in wolves:
        players[pid] = Player(id=pid, pseudo=pid, is_human=False, role=Role.LOUP, personality=None)
    for pid in others:
        players[pid] = Player(id=pid, pseudo=pid, is_human=False, role=Role.VILLAGEOIS, personality=None)
    return GameState(players=players, phase=Phase.NUIT_LOUPS, cycle=1)


def action(target: str) -> dict:
    return {"message": None, "action": {"type": "night_kill_target", "target": target}}


class ScriptedWolfProvider:
    def __init__(self, scripts: dict[str, list[dict | None]]):
        self.scripts = scripts

    def get_action(self, player_id, context):
        return self.scripts[player_id].pop(0)


def test_wolves_agree_immediately_on_the_same_target():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4"])
    provider = ScriptedWolfProvider({
        "ia_1": [{"message": "ia_3", "action": {"type": "night_kill_target", "target": "ia_3"}}],
        "ia_2": [{"message": None, "action": {"type": "night_kill_target", "target": "ia_3"}}],
    })
    assert resolve_wolf_phase(state, provider, rng=random.Random(1)) == "ia_3"
    assert {"author": "ia_1", "text": "ia_3"} in state.wolf_room_log


def test_wolves_negotiate_up_to_three_rounds_then_agree():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4"])
    provider = ScriptedWolfProvider({
        "ia_1": [action("ia_3")] * 2 + [action("ia_4")],
        "ia_2": [action("ia_4")] * 3,
    })
    # ia_1 switches to ia_4 on round 3, matching ia_2
    assert resolve_wolf_phase(state, provider, rng=random.Random(1)) == "ia_4"


def test_wolves_still_disagreeing_after_three_rounds_triggers_tiebreak():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4"])
    provider = ScriptedWolfProvider({
        "ia_1": [action("ia_3")] * 3,
        "ia_2": [action("ia_4")] * 3,
    })
    result = resolve_wolf_phase(state, provider, rng=random.Random(1))
    assert result in {"ia_3", "ia_4"}


def test_a_wolf_attempting_to_target_the_other_wolf_is_treated_as_no_submission():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3"])
    provider = ScriptedWolfProvider({
        "ia_1": [action("ia_2")] * 3,   # illégal à chaque tour
        "ia_2": [action("ia_3")] * 3,
    })
    result = resolve_wolf_phase(state, provider, rng=random.Random(1))
    assert result == "ia_3"  # seul candidat légal jamais proposé


def test_silent_wolves_fall_back_to_a_random_alive_non_wolf():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4"])
    provider = ScriptedWolfProvider({"ia_1": [None] * 3, "ia_2": [None] * 3})
    result = resolve_wolf_phase(state, provider, rng=random.Random(1))
    assert result in {"ia_3", "ia_4"}


def test_a_wolf_claiming_a_mismatched_action_type_is_treated_as_no_submission():
    # La réponse d'ia_1 annonce action.type "day_vote" (ciblant ia_4) alors
    # que le moteur demande night_kill_target : ça ne doit pas être
    # réinterprété silencieusement comme une proposition de nuit sur ia_4
    # juste parce qu'elle porte une cible que le moteur accepterait
    # autrement. Si c'était accepté à tort, ia_1 et ia_2 seraient en
    # désaccord permanent (ia_4 contre ia_3) et le tirage au sort pourrait
    # choisir l'un ou l'autre ; avec le décalage correctement rejeté, ia_1
    # ne contribue jamais, donc ia_3 d'ia_2 est la seule proposition
    # valide jamais faite et gagne de façon déterministe quelle que soit
    # la graine aléatoire.
    for seed in range(20):
        state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4"])
        provider = ScriptedWolfProvider({
            "ia_1": [{"message": None, "action": {"type": "day_vote", "target": "ia_4"}}] * 3,
            "ia_2": [action("ia_3")] * 3,
        })
        result = resolve_wolf_phase(state, provider, rng=random.Random(seed))
        assert result == "ia_3", f"seed {seed} let a mismatched action.type through as {result!r}"


def test_tiebreak_only_considers_each_wolfs_last_proposal_not_every_round():
    # Design §2a : "le moteur tire au sort entre les deux dernières cibles
    # proposées". ia_1 propose une cible DIFFÉRENTE à chaque tour (ia_3,
    # puis ia_4, puis ia_5) tandis qu'ia_2 propose toujours ia_6 (toujours
    # en désaccord, donc l'accord n'arrive jamais et les 3 tours se
    # déroulent). Le tirage au sort ne doit jamais pouvoir choisir qu'entre
    # la DERNIÈRE proposition d'ia_1 (ia_5) et la dernière d'ia_2 (ia_6) --
    # jamais ia_3 ou ia_4, qui étaient des propositions abandonnées des
    # tours précédents.
    for seed in range(30):
        state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4", "ia_5", "ia_6"])
        provider = ScriptedWolfProvider({
            "ia_1": [action("ia_3"), action("ia_4"), action("ia_5")],
            "ia_2": [action("ia_6")] * 3,
        })
        result = resolve_wolf_phase(state, provider, rng=random.Random(seed))
        assert result in {"ia_5", "ia_6"}, f"seed {seed} picked abandoned proposal {result!r}"


def test_a_dead_wolf_is_never_asked_for_a_target_and_the_lone_survivor_can_agree_with_itself():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4"])
    state.get("ia_1").alive = False
    # Le script d'ia_2 n'a qu'une seule entrée : si resolve_wolf_phase
    # exigeait les 3 tours complets (ancien comportement comparé à
    # l'effectif complet des 2 loups), ça lèverait IndexError au deuxième
    # tour. ia_1 n'a aucun script du tout : si on l'appelait jamais (un
    # loup mort sollicité pour une cible), dépiler d'une liste vide lève
    # immédiatement KeyError/IndexError.
    provider = ScriptedWolfProvider({"ia_1": [], "ia_2": [action("ia_3")]})
    result = resolve_wolf_phase(state, provider, rng=random.Random(1))
    assert result == "ia_3"
