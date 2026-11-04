from django.urls import path

from game import views

urlpatterns = [
    path("", views.home, name="home"),
    path("confidentialite/", views.privacy, name="privacy"),
    path("jouer/", views.play, name="play"),
    path("nouvelle-partie/", views.new_game, name="new_game"),
    path("abandonner/", views.abandon, name="abandon"),
]
