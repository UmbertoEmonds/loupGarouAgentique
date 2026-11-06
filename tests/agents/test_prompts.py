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
