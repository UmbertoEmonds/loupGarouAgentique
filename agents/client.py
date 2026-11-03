import os

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterError(Exception):
    pass


class OpenRouterClient:
    def __init__(
        self,
        model: str | None = None,
        fallback_model: str | None = None,
        timeout: float = 15.0,
        api_key: str | None = None,
        session=None,
    ):
        self.model = model if model is not None else os.environ.get("OPENROUTER_MODEL")
        self.fallback_model = (
            fallback_model if fallback_model is not None
            else os.environ.get("OPENROUTER_FALLBACK_MODEL")
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

        A non-200 status and a 200 response with an unexpected body are both
        treated as a failed attempt.
        """
        response = self._post(model, system_prompt, user_content)
        if response.status_code != 200:
            return None
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError):
            return None
        return content if isinstance(content, str) else None

    def complete(self, system_prompt: str, user_content: str) -> str:
        content = self._attempt(self.model, system_prompt, user_content)
        if content is not None:
            return content

        if self.fallback_model:
            content = self._attempt(self.fallback_model, system_prompt, user_content)
            if content is not None:
                return content

        raise OpenRouterError("OpenRouter request failed on all configured models")
