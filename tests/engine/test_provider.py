from engine.provider import request_with_retry


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
    def get_action(self, player_id, context):
        self.calls += 1
        return self.responses.pop(0)

def test_request_with_retry_returns_first_success():
    provider = ScriptedProvider([{"message": None, "action": None}])
    result = request_with_retry(provider, "ia_1", {}, attempts=2)
    assert result == {"message": None, "action": None}
    assert provider.calls == 1

def test_request_with_retry_retries_once_after_a_none():
    provider = ScriptedProvider([None, {"message": "ok", "action": None}])
    result = request_with_retry(provider, "ia_1", {}, attempts=2)
    assert result == {"message": "ok", "action": None}
    assert provider.calls == 2

def test_request_with_retry_gives_up_after_attempts_exhausted():
    provider = ScriptedProvider([None, None])
    result = request_with_retry(provider, "ia_1", {}, attempts=2)
    assert result is None
    assert provider.calls == 2
