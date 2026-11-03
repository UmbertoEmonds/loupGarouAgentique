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
