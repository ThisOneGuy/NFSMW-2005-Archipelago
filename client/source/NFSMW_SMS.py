import asyncio
import logging
import re

log = logging.getLogger("NFSMW")


def item_sms_id(key):
    return (
        isinstance(key, str)
        and re.fullmatch(r"(?:recv:[0-9]+|sent:-?[0-9]+:-?[0-9]+:-?[0-9]+:-?[0-9]+)", key)
        is not None
    )


class NFSMWSMSMixin:
    def load_sms_state(self, data):
        self.sms_acknowledged = {
            key for key in data.get("sms_acknowledged", []) if item_sms_id(key) and len(key) <= 160
        }
        self.sms_pending = {
            key: value
            for key, value in data.get("sms_pending", {}).items()
            if item_sms_id(key)
            and isinstance(value, dict)
            and key == value.get("id")
            and key not in self.sms_acknowledged
            and value.get("session_key") == self.session_key
            and value.get("type") == "sms_notification"
        }

    async def queue_sms(self, key, sender, recipient, game, body, item_name=""):
        if not item_sms_id(key) or not self.session_key or not self._session_state_loaded:
            return
        if key in self.sms_acknowledged:
            return
        if key not in self.sms_pending:
            self.sms_pending[key] = {
                "type": "sms_notification",
                "id": key,
                "session_key": self.session_key,
                "from": sender,
                "to": recipient,
                "subject": game,
                "body": body,
                "item_name": item_name,
            }

        if not self._save_state():
            log.warning("SMS retained in memory; client state could not be saved.")
            return
        await self.broadcast(self.sms_pending[key])

    async def queue_received_sms(self, index, item):
        sender = item.get("source_name") or "Archipelago"
        name = item.get("item_name") or "Unknown item"
        await self.queue_sms(
            f"recv:{index}",
            sender,
            self.slot_name,
            self.game,
            f"{sender} has sent {name} to you.",
            name,
        )

    async def replay_sms(self):
        if not self.sms_pending:
            return
        if self._save_state():
            for packet in list(self.sms_pending.values()):
                await self.broadcast(packet)

    def acknowledge_sms(self, packet):
        key = packet.get("id")
        if packet.get("session_key") != self.session_key or key not in self.sms_pending:
            return
        row = self.sms_pending.pop(key)
        self.sms_acknowledged.add(key)
        if not self._save_state():
            self.sms_acknowledged.discard(key)
            self.sms_pending[key] = row

    def on_print_json(self, args):

        super().on_print_json(args)
        if args.get("type") != "ItemSend" or not self.session_key:
            return
        item = args.get("item")
        try:
            if isinstance(item, dict):
                item_id, location, source = (
                    int(item["item"]),
                    int(item["location"]),
                    int(item["player"]),
                )
            elif hasattr(item, "item"):
                item_id, location, source = int(item.item), int(item.location), int(item.player)
            else:
                item_id, location, source = map(int, item[:3])
            receiving = int(args["receiving"])
        except (KeyError, TypeError, ValueError, IndexError):
            return

        if source != self.slot and not self.slot_concerns_self(source):
            return
        if receiving == self.slot or self.slot_concerns_self(receiving):
            return
        recipient = self._player_name(receiving)
        game = self._slot_game(receiving)
        name = self._resolve_item_name(item_id, game)
        asyncio.create_task(
            self.queue_sms(
                f"sent:{source}:{location}:{receiving}:{item_id}",
                self.slot_name,
                recipient,
                game,
                f"You have sent {name} to {recipient}.",
                name,
            )
        )
