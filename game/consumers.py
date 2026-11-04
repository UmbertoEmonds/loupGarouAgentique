import asyncio
import time

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from game.session import GROUP, session


class GameConsumer(AsyncJsonWebsocketConsumer):
    """Un seul salon global : tous les messages passent par le groupe `game`.

    Seul le propriétaire de la partie (cookie de session) peut agir ; les autres
    visiteurs sont refusés à la connexion.
    """

    async def connect(self):
        if not session.is_owner(self.scope["session"].get("player_key")):
            await self.close(code=4403)
            return
        session.loop = asyncio.get_running_loop()
        await self.channel_layer.group_add(GROUP, self.channel_name)
        await self.accept()
        await self.send_json({"type": "state", "payload": session.snapshot(), "server_time": time.time()})

    async def disconnect(self, code):
        await self.channel_layer.group_discard(GROUP, self.channel_name)

    async def game_state(self, event):
        await self.send_json({"type": "state", "payload": event["payload"], "server_time": time.time()})

    async def receive_json(self, content, **kwargs):
        if content.get("type") != "answer" or session.human is None:
            return
        error = session.human.submit(content.get("request_id", ""), content)
        if error:
            await self.send_json({"type": "error", "message": error})
