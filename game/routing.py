from django.urls import path

from game.consumers import GameConsumer

websocket_urlpatterns = [path("ws/game/", GameConsumer.as_asgi())]
