from NFSMW_EventPermits import events_available


def field(row, key, default=None):
    return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)


def received_car_names(ctx):
    manifest = getattr(ctx, "item_manifest", {})
    return {
        field(meta, "car", "")
        for item in getattr(ctx, "items_received", ())
        if (meta := manifest.get(field(item, "item"))) is not None
        and field(meta, "item_type", field(meta, "type")) == "car"
    }


def visual_scout_access(ctx, location, blacklist=None):
    settings = getattr(ctx, "slot_data", {}) or {}
    if not settings.get("reveal_event_rewards", False):
        return False, "Reward reveals are disabled for this seed."
    if location not in getattr(ctx, "server_locations", set()):
        return False, "This location is not in your current seed."
    shop = getattr(ctx, "shop_locations", {}).get(location)
    if shop is not None:
        if field(shop, "car", "") in received_car_names(ctx):
            return True, ""
        return False, "Receive this car before revealing its shop rewards."
    entry = (blacklist or {}).get(location)
    if entry is None:
        return False, "Choose a check from your current seed."
    rank, _ = entry
    if not events_available(settings, getattr(ctx, "items_received", ()), rank):
        return False, "Receive this rival's Event Permit first."
    rival = any(
        field(meta, "location_id") == location and (field(meta, "mapping_source") == "rival_race" or str(field(meta, "event_id", "")).endswith(".r"))
        for meta in getattr(ctx, "event_map", {}).values()
    )
    rival = rival or location in (2600001 + (16 - rank) * 10, 2600002 + (16 - rank) * 10)
    if rival and settings.get("randomize_blacklist_unlocks", False):
        received = {field(item, "item") for item in getattr(ctx, "items_received", ())}
        if 1300000 + rank not in received:
            return False, "Receive this rival's Rival Challenge Permit first."
    return True, ""
