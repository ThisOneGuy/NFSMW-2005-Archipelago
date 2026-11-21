from __future__ import annotations
import time
import uuid
from NFSMW_ScoutAccess import field, visual_scout_access
from NFSMW_StoreRoutes import route_shop, shop_randomized


def received_cars(ctx):
    cars = {}
    for index, item in enumerate(getattr(ctx, "items_received", ())):
        item_id = field(item, "item")
        meta = getattr(ctx, "item_manifest", {}).get(item_id)
        if meta is not None and field(meta, "item_type") == "car":
            cars[field(meta, "car")] = (item_id, index)
    return cars


def seed_shop_cars(ctx):
    settings = getattr(ctx, "slot_data", {}) or {}
    locations = getattr(ctx, "server_locations", set())
    cars = {}
    for location, meta in getattr(ctx, "shop_locations", {}).items():
        if location not in locations or field(meta, "location_type") == "dealership":
            continue
        row = {
            "car": field(meta, "car"),
            "location_type": field(meta, "location_type"),
            "category": field(meta, "category"),
            "tier": field(meta, "tier"),
        }
        if row["car"] and shop_randomized(row, settings):
            cars[row["car"]] = cars.get(row["car"], 0) + 1
    return cars


def live_garage(ctx):
    state = getattr(ctx, "garage_state", {})
    fresh = (
        ctx.ap_connected()
        and bool(getattr(ctx, "game_ready_pids", set()))
        and state.get("session_key") == getattr(ctx, "session_key", "")
        and time.monotonic() - state.get("observed_at", 0) < 5.0
        and state.get("available") is True
    )
    return state if fresh else {}


def resend_status(ctx, car):
    receipt = received_cars(ctx).get(car)
    if receipt is None:
        return False, "This car has not been received from Archipelago."
    if not ctx.ap_connected():
        return False, "Disconnected from your Archipelago session."
    state = live_garage(ctx)
    if not state:
        return False, "Waiting for the game's garage."
    if car in state.get("cars", ()):
        return False, "Already in your in-game garage."
    if receipt[1] not in getattr(ctx, "delivered_received_indices", set()):
        return False, "First delivery is queued. Open the safehouse with a free space."
    pending = getattr(ctx, "garage_pending", {}).get(car)
    if car in state.get("pending_cars", ()) or (
        pending and time.monotonic() - pending["sent_at"] < 10.0
    ):
        return False, (
            "Re-send queued. Sell a car to free a space."
            if state.get("free_slots", 0) < 1
            else "Re-send queued. Open the safehouse to receive it."
        )
    if state.get("resend_supported") is not True:
        return False, "Car re-send is unavailable. Check the game's mod files and save folder."
    if state.get("can_deliver") is not True:
        return False, "Open the safehouse to re-send this car."
    if state.get("free_slots", 0) < 1:
        return True, "Garage full. Request a re-send, then sell a car to free a space."
    return True, "Re-send for free. Re-sent models sell for $0 for this seed."


def local_upgrade_locations(ctx, blacklist, hints):
    if not ctx.ap_connected():
        return {}
    candidates = {}
    for catalog in (getattr(ctx, "shop_catalog", {}), getattr(ctx, "reward_catalog", {})):
        for location, reward in catalog.items():
            if field(reward, "recipient_player") == ctx.slot:
                candidates.setdefault(location, set()).add(field(reward, "item_id"))
    for hint in hints:
        if hint.get("finding_player") == ctx.slot and hint.get("receiving_player") == ctx.slot:
            candidates.setdefault(hint["location"], set()).add(hint["item"])
    for item in getattr(ctx, "items_received", ()):
        if field(item, "player") == ctx.slot:
            candidates.setdefault(field(item, "location"), set()).add(field(item, "item"))
    result = {}
    for location, items in candidates.items():
        if not visual_scout_access(ctx, location, blacklist)[0]:
            continue
        for item in items:
            if isinstance(item, int):
                result.setdefault(item, set()).add(location)
    return result


def garage_snapshot(ctx, blacklist, hints):
    cars = received_cars(ctx)
    shop_cars = seed_shop_cars(ctx)
    car_items = {
        field(meta, "car"): item_id
        for item_id, meta in getattr(ctx, "item_manifest", {}).items()
        if field(meta, "item_type") == "car"
    }
    received = {field(item, "item") for item in getattr(ctx, "items_received", ())}
    local = local_upgrade_locations(ctx, blacklist, hints)
    state = live_garage(ctx)
    settings = getattr(ctx, "slot_data", {})
    rows = []
    for car in sorted(set(cars) | set(shop_cars)):
        item_id, index = cars.get(car, (car_items.get(car), None))
        allowed, reason = resend_status(ctx, car)
        upgrades = []
        for upgrade_id, meta in getattr(ctx, "item_manifest", {}).items():
            if field(meta, "car") != car or field(meta, "item_type") != "performance_part":
                continue
            route = route_shop(
                {
                    "car": car,
                    "location_type": "performance_shop",
                    "category": field(meta, "category"),
                    "tier": field(meta, "tier"),
                }
            )
            randomized = shop_randomized(route, settings)
            owned = upgrade_id in received
            locations = sorted(local.get(upgrade_id, ())) if randomized else []
            upgrades.append(
                {
                    "item_id": upgrade_id,
                    "name": route["slot_label"],
                    "group": route["store_group"],
                    "received": owned,
                    "local": bool(locations),
                    "local_locations": locations,
                    "randomized": randomized,
                    "status": (
                        "Received" if owned
                        else "Not received" if randomized
                        else "Available from start"
                    ),
                }
            )
        in_game = car in state.get("cars", ()) if state else None
        upgrades.sort(key=lambda part: (part["group"], part["item_id"]))
        rows.append(
            {
                "name": car,
                "item_id": item_id,
                "receipt_index": index,
                "received": car in cars,
                "has_shop_locations": car in shop_cars,
                "shop_location_count": shop_cars.get(car, 0),
                "in_game": in_game,
                "delivery_pending": index is not None and index not in getattr(ctx, "delivered_received_indices", set()),
                "no_resale": car in state.get("no_resale_cars", ()),
                "can_resend": allowed,
                "resend_reason": reason,
                "upgrades": upgrades,
            }
        )
    return {
        "available": bool(state),
        "count": state.get("count"),
        "capacity": 25,
        "shop_cars": sorted(shop_cars),
        "cars": rows,
    }


class NFSMWGarageMixin:
    def reset_garage(self):
        self.garage_state = {}
        self.garage_pending = {}

    def accept_garage_state(self, msg):
        cars = msg.get("cars")
        no_resale = msg.get("no_resale_cars")
        pending = msg.get("pending_cars", "")
        count = msg.get("count")
        free = msg.get("free_slots")
        if (
            msg.get("session_key") != self.session_key
            or not self.session_key
            or not isinstance(cars, str)
            or not isinstance(no_resale, str)
            or not isinstance(pending, str)
            or not isinstance(count, int)
            or not isinstance(free, int)
            or not 0 <= count <= 25
            or free != 25 - count
        ):
            return False
        self.garage_state = {
            "session_key": self.session_key,
            "available": msg.get("available") is True,
            "resend_supported": msg.get("resend_supported") is True,
            "can_deliver": msg.get("can_deliver") is True,
            "count": count,
            "free_slots": free,
            "cars": set(cars.split("|")) - {""},
            "no_resale_cars": set(no_resale.split("|")) - {""},
            "pending_cars": set(pending.split("|")) - {""},
            "observed_at": time.monotonic(),
        }
        return True

    async def request_garage_resend(self, car):
        allowed, reason = resend_status(self, car)
        if not allowed:
            return {"ok": False, "operation": "garage_resend", "error": reason}
        item_id, _ = received_cars(self)[car]
        request_id = uuid.uuid4().hex
        self.garage_pending[car] = {"request_id": request_id, "sent_at": time.monotonic()}
        try:
            await self.broadcast(
                {
                    "type": "garage_resend",
                    "session_key": self.session_key,
                    "car": car,
                    "item_id": item_id,
                    "request_id": request_id,
                }
            )
        except (OSError, RuntimeError):
            self.garage_pending.pop(car, None)
            return {"ok": False, "operation": "garage_resend", "error": "Could not reach the game. Try again."}
        return {"ok": True, "operation": "garage_resend", "message": "Re-send requested. Waiting for the game."}

    def accept_garage_result(self, msg):
        car = msg.get("car")
        if not isinstance(car, str):
            return False
        pending = self.garage_pending.get(car)
        if (
            msg.get("session_key") != self.session_key
            or not pending
            or pending["request_id"] != msg.get("request_id")
        ):
            return False
        self.garage_pending.pop(car, None)
        if msg.get("status") in ("delivered", "already_owned"):
            self.garage_state.setdefault("cars", set()).add(car)
        self.garage_state["observed_at"] = 0
        return True
