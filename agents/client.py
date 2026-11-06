import os

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
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

    def complete(self, system_prompt: str, user_content: str) -> str:
        for model in self.models:
            content = self._attempt(model, system_prompt, user_content)
            if content is not None:
                return content

        raise self.ERROR_CLS(f"{type(self).__name__} request failed on all configured models")


class OpenRouterClient(_ChatCompletionClient):
    URL = OPENROUTER_URL
    MODELS_ENV_VAR = "OPENROUTER_MODELS"
    API_KEY_ENV_VAR = "OPENROUTER_API_KEY"
    ERROR_CLS = OpenRouterError


class GroqClient(_ChatCompletionClient):
    """Repli quand OpenRouter est hors service (quota du *compte* OpenRouter
    atteint, pas seulement celui d'un modèle — déjà couvert par la liste de
    modèles d'OpenRouterClient). Groq expose une API compatible OpenAI avec
    un palier gratuit sans carte bancaire."""

    URL = GROQ_URL
    MODELS_ENV_VAR = "GROQ_MODELS"
    API_KEY_ENV_VAR = "GROQ_API_KEY"
    ERROR_CLS = GroqError
    DEFAULT_MODELS = ("llama-3.1-8b-instant",)


class FallbackClient:
    """Enchaîne plusieurs clients `complete()` : si le premier échoue (tous
    ses modèles épuisés), tente le suivant. Sert à ajouter un fournisseur de
    secours indépendant (ex: Groq) quand c'est le compte OpenRouter entier
    qui est à quota, pas juste un modèle."""

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
