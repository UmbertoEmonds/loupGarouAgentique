import secrets

from django.conf import settings
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from game.session import session

MAX_PSEUDO_LEN = 20


def _owner(request) -> str | None:
    return request.session.get("player_key")


def privacy(request):
    """Page d'information RGPD / AI Act (statique, accessible sans partie)."""
    return render(request, "game/privacy.html", {"contact_email": settings.PRIVACY_CONTACT_EMAIL})


def home(request):
    mine = session.is_owner(_owner(request))
    busy = session.active and session.running and not mine
    return render(request, "game/home.html", {
        "busy": busy,
        "can_resume": mine and not session.finished,
        "error": request.GET.get("erreur"),
    })


@require_POST
def new_game(request):
    pseudo = " ".join(request.POST.get("pseudo", "").split())[:MAX_PSEUDO_LEN]
    if not pseudo:
        return redirect("/?erreur=pseudo")
    key = _owner(request) or secrets.token_urlsafe(16)
    request.session["player_key"] = key
    if not session.start(key, pseudo):
        return redirect("/?erreur=occupe")
    return redirect("play")


def play(request):
    if not session.is_owner(_owner(request)):
        return redirect("home")
    return render(request, "game/play.html")


@require_POST
def abandon(request):
    if session.is_owner(_owner(request)):
        session.abandon()
    return redirect("home")
