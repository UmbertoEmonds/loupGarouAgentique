"""Réglages Django : un seul process, aucune base de données (état en mémoire)."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or (
    "dev-insecure-key" if DEBUG else "change-me-" + "x" * 40
)

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])
ALLOWED_HOSTS += [h for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h]
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if "." in h and h != "testserver"]

INSTALLED_APPS = [
    "daphne",
    "django.contrib.staticfiles",
    "channels",
    "django_tailwind_cli",
    "game",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

# Pas de BDD : sessions dans un cookie signé, état de partie en mémoire.
DATABASES = {}
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_HTTPONLY = True

# Un seul process => couche de canaux en mémoire (pas de Redis).
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "assets"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# --- Partie ---
# Délai accordé à l'humain pour agir (spec : 60 à 90 s, avec décompte visible).
HUMAN_TIMEOUT_S = int(os.environ.get("HUMAN_TIMEOUT_S", "75"))
DEBATE_DURATION_S = int(os.environ.get("DEBATE_DURATION_S", "180"))
PHASE_PAUSE_S = float(os.environ.get("PHASE_PAUSE_S", "2.5"))
# FAKE_AI=1 : IA scriptée locale, pour tester l'interface sans clé OpenRouter.
# Adresse affichée sur la page de confidentialité pour exercer ses droits (facultatif).
PRIVACY_CONTACT_EMAIL = os.environ.get("PRIVACY_CONTACT_EMAIL", "")
FAKE_AI = os.environ.get("FAKE_AI", "0") == "1"
FAKE_AI_DELAY_S = float(os.environ.get("FAKE_AI_DELAY_S", "0.4"))

TAILWIND_CLI_SRC_CSS = str(BASE_DIR / "game" / "styles" / "source.css")
TAILWIND_CLI_DIST_CSS = "css/tailwind.css"
TAILWIND_CLI_ASSETS_ROOT = str(BASE_DIR / "assets")
