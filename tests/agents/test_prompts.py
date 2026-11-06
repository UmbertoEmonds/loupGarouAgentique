from agents.prompts import (
    PERSONALITY_FRAGMENTS,
    PROMPT_GENERAL_TEMPLATE,
    ROLE_FRAGMENTS,
    assemble_system_prompt,
)
from engine.models import Role


def test_assemble_system_prompt_concatenates_general_role_and_personality_in_order():
    prompt = assemble_system_prompt("Fatima", Role.SORCIERE, "stratege")
    general_pos = prompt.index("Tu es Fatima")
    role_pos = prompt.index(ROLE_FRAGMENTS[Role.SORCIERE])
    personality_pos = prompt.index(PERSONALITY_FRAGMENTS["stratege"])
    assert general_pos < role_pos < personality_pos

def test_general_block_substitutes_the_drawn_name():
    prompt = assemble_system_prompt("Sofia", Role.VILLAGEOIS, "paranoiaque")
    assert "Tu es Sofia" in prompt
    assert "{nom}" not in prompt

def test_role_fragments_cover_exactly_the_three_roles():
    assert set(ROLE_FRAGMENTS) == {Role.LOUP, Role.SORCIERE, Role.VILLAGEOIS}

def test_personality_fragments_cover_exactly_the_five_slugs():
    assert set(PERSONALITY_FRAGMENTS) == {"mauvais_joueur", "stratege", "impatient", "paranoiaque", "manipulateur"}

def test_general_block_states_the_json_response_contract():
    assert '"message"' in PROMPT_GENERAL_TEMPLATE
    assert '"action"' in PROMPT_GENERAL_TEMPLATE

def test_general_block_forbids_denying_being_an_ai():
    assert "intelligence artificielle" in PROMPT_GENERAL_TEMPLATE


def test_the_human_is_not_presented_as_an_opponent():
    # Un loup IA peut avoir l'humain pour allié : le prompt ne doit pas l'opposer d'office.
    assert "contre un joueur humain" not in PROMPT_GENERAL_TEMPLATE
    assert "allié" in PROMPT_GENERAL_TEMPLATE


def test_impulsive_personalities_never_reveal_their_role():
    for slug in ("mauvais_joueur", "impatient", "paranoiaque"):
        fragment = PERSONALITY_FRAGMENTS[slug]
        assert "tu peux révéler ton rôle" not in fragment, slug
        assert "tu ne révèles jamais ton rôle" in fragment, slug


def test_calculated_reveals_remain_possible_for_strategic_personalities():
    for slug in ("stratege", "manipulateur"):
        assert "tu peux révéler ton rôle réel" in PERSONALITY_FRAGMENTS[slug], slug


def test_personality_never_replaces_actual_play():
    assert "ne remplace pas le jeu" in PROMPT_GENERAL_TEMPLATE
    assert "N'invente aucun fait" in PROMPT_GENERAL_TEMPLATE


def test_general_block_does_not_assume_a_public_debate():
    # Les règles du débat (argumenter, réagir à la nuit) vivent dans la scène
    # du jour : dans le bloc général, elles s'appliquaient aussi à l'antre des
    # loups et poussaient à inventer des soupçons la première nuit.
    assert "faire avancer la partie" not in PROMPT_GENERAL_TEMPLATE
    assert "évènements de la nuit" not in PROMPT_GENERAL_TEMPLATE
    assert "la scène t'est décrite" in PROMPT_GENERAL_TEMPLATE


def test_wolves_talk_privately_and_frankly_at_night():
    loup = ROLE_FRAGMENTS[Role.LOUP]
    assert "salon privé que personne d'autre ne lit" in loup
    assert "Inutile de convaincre ou de manipuler" in loup
    assert "personne n'est suspect" in loup
    assert "au hasard, c'est normal" in loup


def test_agents_know_they_cannot_see_the_other_players():
    # Sans ça, un loup imaginait une vraie table : « tout le monde la regarde »,
    # « elle a l'air timide », alors que personne n'avait encore rien écrit.
    assert "Tu ne vois pas les autres joueurs" in PROMPT_GENERAL_TEMPLATE


def test_personality_reflexes_are_tied_to_the_debate():
    # La première nuit, personne n'a hésité ni parlé : ces réflexes ne valent que pour le débat.
    assert "pendant le débat, tu accuses sur une simple impression" in PERSONALITY_FRAGMENTS["mauvais_joueur"]
    assert "Pendant le débat, tu soupçonnes" in PERSONALITY_FRAGMENTS["impatient"]
    assert "Dans le débat, tu interprètes chaque silence" in PERSONALITY_FRAGMENTS["paranoiaque"]


def test_out_of_universe_wording_is_forbidden():
    assert "univers du village" in PROMPT_GENERAL_TEMPLATE


def test_grammatical_gender_follows_the_character():
    assert "une joueuse" in assemble_system_prompt("Ines", Role.VILLAGEOIS, "stratege")
    assert "une joueuse" in assemble_system_prompt("Sarah", Role.LOUP, "impatient")
    assert "un joueur" in assemble_system_prompt("Benji", Role.VILLAGEOIS, "stratege")


def test_impulsive_reflexes_are_triggered_by_the_situation():
    assert "dès que le débat traîne" in PERSONALITY_FRAGMENTS["impatient"]
    assert "tu veux voter tout de suite" not in PERSONALITY_FRAGMENTS["impatient"]
    assert "Seulement quand on te soupçonne" in PERSONALITY_FRAGMENTS["mauvais_joueur"]
