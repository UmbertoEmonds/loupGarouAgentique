import os

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterError(Exception):
    pass


def _parse_model_list(value: str | None) -> list[str]:
    """Découpe une chaîne d'identifiants de modèles séparés par des virgules en liste ordonnée.

    Accepte un seul identifiant, plusieurs séparés par des virgules, ou
    None/vide (aucun modèle configuré). Les espaces autour de chaque
    identifiant sont retirés ; les entrées vides (ex: virgule finale)
    sont ignorées.
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
        """Retourne le texte de l'assistant, ou None si la tentative a échoué.

        Un statut autre que 200, une réponse 200 au corps inattendu, et une
        erreur réseau (timeout, connexion, ...) levée par l'appel HTTP
        lui-même sont tous traités de façon identique comme une tentative
        échouée.
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
