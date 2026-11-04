import pytest

from agents.schema import ResponseParseError, parse_response


def test_parse_response_accepts_a_null_action():
    result = parse_response('{"message": "salut", "action": null}')
    assert result == {"message": "salut", "action": None}

def test_parse_response_accepts_a_structured_action():
    raw = '{"message": null, "action": {"type": "day_vote", "target": "ia_3"}}'
    result = parse_response(raw)
    assert result == {"message": None, "action": {"type": "day_vote", "target": "ia_3"}}

def test_parse_response_rejects_non_json():
    with pytest.raises(ResponseParseError):
        parse_response("ceci n'est pas du JSON")

def test_parse_response_rejects_missing_keys():
    with pytest.raises(ResponseParseError):
        parse_response('{"message": "salut"}')

def test_parse_response_rejects_unknown_action_type():
    with pytest.raises(ResponseParseError):
        parse_response('{"message": null, "action": {"type": "fly_away", "target": null}}')

def test_parse_response_rejects_surrounding_prose():
    with pytest.raises(ResponseParseError):
        parse_response('Voici ma réponse: {"message": null, "action": null}')

def test_parse_response_rejects_non_dict_top_level_json():
    with pytest.raises(ResponseParseError):
        parse_response('["salut", null]')
    with pytest.raises(ResponseParseError):
        parse_response('"salut"')

def test_parse_response_rejects_extra_top_level_keys():
    with pytest.raises(ResponseParseError):
        parse_response('{"message": null, "action": null, "extra": 1}')

def test_parse_response_rejects_non_string_message():
    with pytest.raises(ResponseParseError):
        parse_response('{"message": 42, "action": null}')

def test_parse_response_rejects_action_missing_target_key():
    with pytest.raises(ResponseParseError):
        parse_response('{"message": null, "action": {"type": "day_vote"}}')

def test_parse_response_rejects_action_with_wrong_target_type():
    with pytest.raises(ResponseParseError):
        parse_response('{"message": null, "action": {"type": "day_vote", "target": 3}}')

def test_parse_response_rejects_non_dict_action():
    with pytest.raises(ResponseParseError):
        parse_response('{"message": null, "action": "day_vote"}')

def test_parse_response_rejects_pass_action_type_absent_from_enum():
    with pytest.raises(ResponseParseError):
        parse_response('{"message": null, "action": {"type": "pass", "target": null}}')

def test_parse_response_rejects_unhashable_action_type():
    with pytest.raises(ResponseParseError):
        parse_response('{"message": null, "action": {"type": ["day_vote"], "target": null}}')

def test_parse_response_rejects_a_message_dominated_by_chinese_characters():
    raw = '{"message": "安静注视却以为那只是静观之密。好了 每天一起团结", "action": null}'
    with pytest.raises(ResponseParseError):
        parse_response(raw)

def test_parse_response_rejects_a_message_mixing_french_and_chinese():
    raw = (
        '{"message": "Entendez-vous, ne faites pas semblant que Jean avait '
        'disparu par hasard ? 限定于新计划小人物当一座大城市的杀手在市民倒下后召开了会议讨论如何联合同一个敌人", '
        '"action": null}'
    )
    with pytest.raises(ResponseParseError):
        parse_response(raw)

def test_parse_response_accepts_a_normal_french_message():
    result = parse_response('{"message": "Je pense que c\'est Ethan le loup.", "action": null}')
    assert result["message"] == "Je pense que c'est Ethan le loup."

def test_parse_response_accepts_a_french_message_with_guillemets_and_a_name():
    raw = '{"message": "« Bon, on vote ? » a dit Zhāng, un peu vite à mon goût.", "action": null}'
    result = parse_response(raw)
    assert "Zhāng" in result["message"]

def test_parse_response_accepts_null_message_unaffected_by_the_language_check():
    result = parse_response('{"message": null, "action": {"type": "day_vote", "target": "ia_3"}}')
    assert result["message"] is None
