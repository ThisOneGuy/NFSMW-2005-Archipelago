from NFSMW_Goals import existing_blacklist_mask, existing_blacklist_ranks

EVENT_PERMIT_BASE = 1310000
PROGRESSIVE_EVENT_PERMIT = 1310100
PROGRESSIVE_EVENT_NAME = "Progressive Blacklist Event Permit"
EVENT_PERMIT_MODES = ("disabled", "individual", "progressive")


def event_permit_mode(slot_data):
    mode = slot_data.get("blacklist_event_permits", "disabled")
    return mode if mode in EVENT_PERMIT_MODES else "disabled"


def event_permit_name(rank):
    return f"Blacklist #{rank} Event Permit"


def event_permit_requirement(mode, rank):
    if mode == "disabled" or rank == 15:
        return None
    if not 1 <= rank <= 14:
        return None
    if mode == "individual":
        return event_permit_name(rank), 1
    if mode == "progressive":
        return PROGRESSIVE_EVENT_NAME, 15 - rank
    return None


def event_permit_mask(slot_data, items):
    existing = existing_blacklist_mask(slot_data)
    mode = event_permit_mode(slot_data)
    if mode == "disabled":
        return existing
    received = [
        item.get("item", 0) if isinstance(item, dict) else getattr(item, "item", 0)
        for item in items
    ]
    if mode == "progressive":
        count = min(14, received.count(PROGRESSIVE_EVENT_PERMIT))
        return existing & sum(1 << rank for rank in range(15 - count, 16))
    return (1 << 15) | sum(
        1 << rank
        for rank in existing_blacklist_ranks(slot_data)
        if rank != 15 and EVENT_PERMIT_BASE + rank in received
    )


def events_available(slot_data, items, rank):
    return 1 <= rank <= 15 and bool(event_permit_mask(slot_data, items) & (1 << rank))
