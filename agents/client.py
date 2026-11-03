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

    def complete(self, system_prompt: str, user_content: str) -> str:
        response = self._post(self.model, system_prompt, user_content)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]

        if self.fallback_model:
            response = self._post(self.fallback_model, system_prompt, user_content)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]

        raise OpenRouterError(f"OpenRouter request failed (status {response.status_code})")
