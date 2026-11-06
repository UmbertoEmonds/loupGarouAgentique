import os
import time

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Un quota par minute se libère toujours en moins d'une minute. Au-delà, le
# 429 signale un quota du jour épuisé (attente de plusieurs minutes) : inutile
# d'attendre, on passe au fournisseur suivant.
MAX_RATE_LIMIT_WAIT_S = 60.0
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMProviderError(Exception):
    """Base commune : une tentative d'appel à un fournisseur de LLM a échoué
    sur tous ses modèles configurés. Permet à FallbackClient de passer au
    fournisseur suivant sans connaître le type d'erreur précis."""


class OpenRouterError(LLMProviderError):
    pass


class GroqError(LLMProviderError):
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


class _ChatCompletionClient:
    """Base partagée par les clients de fournisseurs LLM "chat completions"
    façon OpenAI (model + messages, header Authorization Bearer) : seuls
    l'URL, les variables d'environnement et le type d'erreur changent d'un
    fournisseur à l'autre (OpenRouter, Groq, ...). Une sous-classe définit
    URL, MODELS_ENV_VAR, API_KEY_ENV_VAR, ERROR_CLS, et éventuellement
    DEFAULT_MODELS (utilisés si la variable d'environnement de modèles est
    absente et qu'aucune liste n'est passée explicitement)."""

    URL: str
    MODELS_ENV_VAR: str
    API_KEY_ENV_VAR: str
    ERROR_CLS: type[LLMProviderError] = LLMProviderError
    DEFAULT_MODELS: tuple[str, ...] = ()

    def __init__(
        self,
        models: list[str] | None = None,
        timeout: float = 15.0,
        api_key: str | None = None,
        session=None,
        on_usage=None,
        on_call=None,
        sleep=time.sleep,
    ):
        self.models = (
            models if models is not None
            else _parse_model_list(os.environ.get(self.MODELS_ENV_VAR)) or list(self.DEFAULT_MODELS)
        )
        self.api_key = api_key if api_key is not None else os.environ.get(self.API_KEY_ENV_VAR)
        self.timeout = timeout
        self.session = session if session is not None else requests.Session()
        # Rappel optionnel recevant le dict `usage` (jetons) de chaque appel réussi.
        self.on_usage = on_usage
        # Rappel optionnel (modèle réellement utilisé, usage) de chaque appel réussi.
        self.on_call = on_call
        self._sleep = sleep
        # Attente demandée par le dernier refus pour quota par minute (429), sinon None.
        self._retry_after: float | None = None

    def _post(self, model: str, system_prompt: str, user_content: str):
        return self.session.post(
            self.URL,
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
        if response.status_code == 429:
            self._retry_after = self._parse_retry_after(response)
            return None
        if response.status_code != 200:
            return None
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError):
            return None
        if not isinstance(content, str):
            return None
        self._report_usage(body)
        self._report_call(model, body)
        return content

    def _report_usage(self, body) -> None:
        if self.on_usage is None or not isinstance(body, dict):
            return
        try:
            self.on_usage(body.get("usage"))
        except Exception:
            # Le suivi des coûts ne doit jamais faire échouer un appel au LLM.
            pass

    def _report_call(self, requested_model: str, body) -> None:
        if self.on_call is None or not isinstance(body, dict):
            return
        try:
            # OpenRouter indique le modèle réellement servi, qui peut différer de celui demandé.
            model = body.get("model") if isinstance(body.get("model"), str) else requested_model
            self.on_call(model, body.get("usage"))
        except Exception:
            pass  # l'affichage ne doit jamais faire échouer un appel au LLM

    @staticmethod
    def _parse_retry_after(response) -> float | None:
        try:
            return float((getattr(response, "headers", None) or {}).get("retry-after"))
        except (TypeError, ValueError):
            return None

    def _try_each_model(self, system_prompt: str, user_content: str) -> tuple[str | None, float | None]:
        """Un passage sur tous les modèles. Retourne (texte, None) au premier
        succès, sinon (None, plus courte attente demandée par un quota par minute)."""
        shortest_wait = None
        for model in self.models:
            self._retry_after = None
            content = self._attempt(model, system_prompt, user_content)
            if content is not None:
                return content, None
            wait = self._retry_after
            if wait is not None and wait <= MAX_RATE_LIMIT_WAIT_S:
                shortest_wait = wait if shortest_wait is None else min(shortest_wait, wait)
        return None, shortest_wait

    def complete(self, system_prompt: str, user_content: str) -> str:
        content, wait = self._try_each_model(system_prompt, user_content)
        if content is None and wait is not None:
            # Tous les modèles sont saturés pour quelques secondes (quota par
            # minute) : on attend une fois puis on retente, plutôt que de faire
            # « passer » le joueur. Sans ça, le débat s'effondrait en 2 s.
            self._sleep(wait)
            content, _ = self._try_each_model(system_prompt, user_content)
        if content is not None:
            return content

        raise self.ERROR_CLS(f"{type(self).__name__} request failed on all configured models")


class OpenRouterClient(_ChatCompletionClient):
    """Secours quand tous les modèles Groq sont à quota : modèles gratuits
    (« :free ») nommés explicitement, puis le routeur « openrouter/free » en
    dernier recours. Ce routeur tombe sur des modèles au hasard (parfois
    chinois), mais il répondait encore quand les modèles nommés avaient
    atteint la limite de 50 requêtes par jour du compte sans crédit."""

    URL = OPENROUTER_URL
    MODELS_ENV_VAR = "OPENROUTER_MODELS"
    API_KEY_ENV_VAR = "OPENROUTER_API_KEY"
    ERROR_CLS = OpenRouterError


class GroqClient(_ChatCompletionClient):
    """Fournisseur principal : API compatible OpenAI, palier gratuit sans carte
    bancaire. Chaque modèle a son propre quota (environ 1000 requêtes par jour
    et 8000 jetons par minute), d'où une liste de plusieurs modèles."""

    URL = GROQ_URL
    MODELS_ENV_VAR = "GROQ_MODELS"
    API_KEY_ENV_VAR = "GROQ_API_KEY"
    ERROR_CLS = GroqError
    DEFAULT_MODELS = ("qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b")


class FallbackClient:
    """Enchaîne plusieurs clients `complete()` : si le premier échoue (tous
    ses modèles épuisés), tente le suivant. Sert à ajouter un fournisseur de
    secours indépendant (ex: OpenRouter) quand tous les modèles du premier
    fournisseur (Groq) sont à quota."""

    def __init__(self, clients: list):
        if not clients:
            raise ValueError("FallbackClient needs at least one client")
        self.clients = clients

    def complete(self, system_prompt: str, user_content: str) -> str:
        error: LLMProviderError | None = None
        for client in self.clients:
            try:
                return client.complete(system_prompt, user_content)
            except LLMProviderError as exc:
                error = exc
        raise error
