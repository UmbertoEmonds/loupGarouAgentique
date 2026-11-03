from agents.client import OpenRouterError
from agents.provider import AIActionProvider
from engine.models import Role


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
    def complete(self, system_prompt, user_content):
        self.calls.append({"system_prompt": system_prompt, "user_content": user_content})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

def test_get_action_returns_the_parsed_response_on_success():
    client = FakeClient(['{"message": "salut", "action": null}'])
    provider = AIActionProvider(client, {"ia_1": "Fatima"}, {"ia_1": Role.VILLAGEOIS}, {"ia_1": "stratege"})
    context = {"phase": "jour_debat", "alive_players": [{"id": "ia_1", "pseudo": "Fatima"}], "main_room_log": [], "self_role": "villageois"}
    result = provider.get_action("ia_1", context)
    assert result == {"message": "salut", "action": None}

def test_get_action_builds_system_prompt_once_per_player():
    client = FakeClient(['{"message": null, "action": null}'])
    provider = AIActionProvider(client, {"ia_1": "Fatima"}, {"ia_1": Role.SORCIERE}, {"ia_1": "stratege"})
    provider.get_action("ia_1", {"phase": "jour_debat", "alive_players": [], "main_room_log": [], "self_role": "sorciere"})
    assert "Tu es Fatima" in client.calls[0]["system_prompt"]

def test_get_action_tags_chat_history_with_author_attribute():
    client = FakeClient(['{"message": null, "action": null}'])
    provider = AIActionProvider(client, {"ia_1": "Fatima"}, {"ia_1": Role.VILLAGEOIS}, {"ia_1": "stratege"})
    context = {
        "phase": "jour_debat", "self_role": "villageois",
        "alive_players": [{"id": "ia_1", "pseudo": "Fatima"}, {"id": "human", "pseudo": "Umberto"}],
        "main_room_log": [{"author": "human", "text": "je pense que c'est toi"}],
    }
    provider.get_action("ia_1", context)
    assert '<message auteur="Umberto">je pense que c\'est toi</message>' in client.calls[0]["user_content"]

def test_get_action_returns_none_on_openrouter_failure():
    client = FakeClient([OpenRouterError("boom")])
    provider = AIActionProvider(client, {"ia_1": "Fatima"}, {"ia_1": Role.VILLAGEOIS}, {"ia_1": "stratege"})
    result = provider.get_action("ia_1", {"phase": "jour_debat", "alive_players": [], "main_room_log": [], "self_role": "villageois"})
    assert result is None

def test_get_action_returns_none_on_unparseable_response():
    client = FakeClient(["ceci n'est pas du JSON"])
    provider = AIActionProvider(client, {"ia_1": "Fatima"}, {"ia_1": Role.VILLAGEOIS}, {"ia_1": "stratege"})
    result = provider.get_action("ia_1", {"phase": "jour_debat", "alive_players": [], "main_room_log": [], "self_role": "villageois"})
    assert result is None
