"""Crée le compte admin à partir de variables d'environnement, s'il n'existe pas.

L'offre gratuite de Render n'a pas de shell pour lancer `createsuperuser` :
cette commande tourne donc au build. Sans DJANGO_SUPERUSER_USERNAME et
DJANGO_SUPERUSER_PASSWORD, elle ne fait rien ; un compte existant n'est
jamais modifié.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crée le superutilisateur décrit par DJANGO_SUPERUSER_USERNAME / _PASSWORD s'il n'existe pas."

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        if not username or not password:
            self.stdout.write("ensure_admin : variables absentes, aucun compte créé.")
            return
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            self.stdout.write(f"ensure_admin : le compte « {username} » existe déjà.")
            return
        User.objects.create_superuser(username, os.environ.get("DJANGO_SUPERUSER_EMAIL", ""), password)
        self.stdout.write(self.style.SUCCESS(f"ensure_admin : compte « {username} » créé."))
