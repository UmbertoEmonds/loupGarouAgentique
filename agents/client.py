import os

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterError(Exception):
    pass


def _parse_model_list(value: str | None) -> list[str]:
    """Split a comma-separated model-id string into an ordered list.

    Accepts a single model id, several comma-separated ids, or None/empty
    (no models configured). Whitespace around each id is stripped; empty
    entries (e.g. a trailing comma) are dropped.
    """
    if not value:
        return []
    return [m.strip() for m in value.split(",") if m.strip()]


class OpenRouterClient:
    def __init__(
        self,
        models: list[str] | None = None,
        timeout: float = 15.0,
        api_key: str | None = None,
        session=None,
    ):
        self.models = (
            models if models is not None
            else _parse_model_list(os.environ.get("OPENROUTER_MODELS"))
        )
        self.api_key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY")
        self.timeout = timeout
        self.session = session if session is not None else requests.Session()

    def _post(self, model: str, system_prompt: str, user_content: str):
        return self.session.post(
            OPENROUTER_URL,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
        )

    def _attempt(self, model: str, system_prompt: str, user_content: str):
        """Return the assistant text, or None if the attempt failed.

        A non-200 status, a 200 response with an unexpected body, and a
        network-level failure (timeout, connection error, ...) raised by the
        HTTP call itself are all treated identically as a failed attempt.
        """
        try:
            response = self._post(model, system_prompt, user_content)
        except requests.RequestException:
            return None
        if response.status_code != 200:
            return None
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError):
            return None
        return content if isinstance(content, str) else None

    def complete(self, system_prompt: str, user_content: str) -> str:
        for model in self.models:
            content = self._attempt(model, system_prompt, user_content)
            if content is not None:
                return content

        raise OpenRouterError("OpenRouter request failed on all configured models")
