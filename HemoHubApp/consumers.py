from channels.generic.websocket import AsyncJsonWebsocketConsumer

NETWORK_GROUP = "network"


class NetworkConsumer(AsyncJsonWebsocketConsumer):
    """Pushes live transfer-network events to every connected blood bank."""

    async def connect(self):
        user = self.scope.get("user")
        if user is None or user.is_anonymous:
            await self.close()
            return
        await self.channel_layer.group_add(NETWORK_GROUP, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(NETWORK_GROUP, self.channel_name)

    # Server -> client. Triggered by channel_layer.group_send(type="network.event").
    async def network_event(self, event):
        await self.send_json(event["payload"])
