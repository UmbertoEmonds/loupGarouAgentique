# Loup-Garou — solo avec des IA

Une partie de Loup-Garou jouable dans le navigateur : **un joueur humain affronte 5 agents IA**, chacun avec sa personnalité, qui débattent, accusent et votent comme de vrais joueurs.

Projet réalisé dans le cadre de la formation Simplon.

## Principe

- **Rôles** : Loup, Villageois, Sorcière.
- **Déroulé** : nuit (les loups choisissent une victime, la sorcière soigne ou empoisonne) → jour (débat libre, puis vote d'élimination) → victoire quand un camp est éliminé.
- **« L'IA propose, le moteur valide »** : les agents répondent en JSON, mais seul le moteur de jeu (côté serveur) modifie l'état de la partie, après validation. Une réponse invalide, trop lente ou en erreur déclenche un repli : la partie ne reste jamais bloquée.
- Le joueur humain dispose d'un délai (60-90 s) avec décompte à l'écran ; au-delà, un repli joue à sa place.

## Architecture

| Dossier | Rôle |
|---|---|
| `engine/` | Moteur de règles autoritaire : état, phases jour/nuit, actions, victoire, repli |
| `agents/` | Agents IA : prompts de personnalité, schéma d'action, client OpenRouter, repli Groq |
| `game/` | Front Django + WebSockets (Channels), templates, Tailwind, session de partie |
| `monitoring/` | Suivi du coût en jetons par manche (modèles Django `Game` / `RoundCost`) |
| `config/` | Réglages Django / ASGI |
| `tests/`, `game/tests/`, `monitoring/tests/` | Tests du moteur, des agents, du front et du suivi des coûts |
| `docs/` | Spécification du moteur, plans, répartition de l'équipe |

Stack : Django 5.2, Django Channels + Daphne, Tailwind (`django-tailwind-cli`), WhiteNoise.
Fournisseurs LLM : OpenRouter (modèles gratuits, avec liste de repli) puis Groq si OpenRouter est à quota.

> L'état de la partie vit **en mémoire** et la couche Channels est `InMemory` : une seule instance, **une seule partie à la fois**.
> La base de données (PostgreSQL en production, SQLite en local) ne sert qu'au suivi des jetons consommés par manche.

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # puis renseigner les clés
python manage.py tailwind build
python manage.py migrate     # crée la base (SQLite local par défaut)
```

Deux fichiers de dépendances :
- `requirements.txt` : ce qu'il faut pour faire tourner l'app (c'est ce que Render installe en production) ;
- `requirements-dev.txt` : reprend `requirements.txt` (`-r`) et ajoute les outils de développement (`pytest`). À utiliser en local.

## Lancer en local

```bash
# Avec une IA scriptée, sans clé API (pratique pour tester l'interface)
FAKE_AI=1 DJANGO_DEBUG=1 python manage.py runserver

# Avec de vrais agents : renseigner OPENROUTER_API_KEY (et GROQ_API_KEY en repli) dans .env
DJANGO_DEBUG=1 python manage.py runserver
```

Puis ouvrir <http://127.0.0.1:8000>.

### Variables d'environnement

| Variable | Description |
|---|---|
| `OPENROUTER_API_KEY` | Clé OpenRouter |
| `OPENROUTER_MODELS` | Modèles séparés par des virgules, essayés dans l'ordre |
| `GROQ_API_KEY` / `GROQ_MODELS` | Repli indépendant si OpenRouter échoue (vide = désactivé) |
| `DJANGO_SECRET_KEY` | Obligatoire en production |
| `DATABASE_URL` | Base PostgreSQL du suivi des coûts (vide = `db.sqlite3` local) |
| `DJANGO_SUPERUSER_USERNAME` / `DJANGO_SUPERUSER_PASSWORD` | Compte de l'admin Django, créé au build par `manage.py ensure_admin` s'il n'existe pas |
| `DJANGO_DEBUG` | `1` en local uniquement |
| `IDLE_ABANDON_S` | Délai (30 s par défaut) sans fenêtre de jeu ouverte avant d'abandonner la partie |
| `FAKE_AI` | `1` pour une IA scriptée locale |
| `HUMAN_TIMEOUT_S` | Délai laissé à l'humain pour agir |
| `DEBATE_DURATION_S` | Durée du débat de jour |

## Suivi des coûts (admin)

Les jetons consommés par manche sont consultables dans l'admin Django, en lecture seule : <http://127.0.0.1:8000/admin/> (en production : `https://<hôte>/admin/`).

```bash
python manage.py createsuperuser   # en local
```

Sur Render (pas de shell sur l'offre gratuite), renseigner `DJANGO_SUPERUSER_USERNAME` et `DJANGO_SUPERUSER_PASSWORD` dans le dashboard : le compte est créé au build suivant.

## Tests

```bash
pytest                      # moteur + agents
python manage.py test game monitoring  # front + suivi des coûts
```

## Déploiement

Configuré pour [Render](https://render.com) (offre gratuite) via `render.yaml` : build Tailwind + `collectstatic`, démarrage par `daphne`. Renseigner les clés API dans le dashboard Render.

## Équipe

- **Umberto** — moteur de jeu et intégration des agents IA
- **Ethan** — front Django/Tailwind, WebSockets, déploiement
