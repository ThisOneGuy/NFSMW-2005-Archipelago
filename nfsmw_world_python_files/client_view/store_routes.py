import re

VISUAL_CATEGORIES = (
    "Body Style",
    "Spoilers",
    "Rim Style",
    "Hoods",
    "Roof Scoops",
    "Body Paint",
    "Vinyls",
    "Rim Color",
    "Window Tint",
)
PERFORMANCE_MENUS = {
    "Engine": 0x201,
    "Transmission": 0x202,
    "Suspension": 0x203,
    "Nitrous": 0x204,
    "Tires": 0x205,
    "Brakes": 0x206,
    "Turbo/Supercharger": 0x207,
}
VISUAL_MENUS = {
    ("Engine", "Race"): 0x101,
    ("Transmission", "Race"): 0x102,
    ("Tires", "Pro"): 0x103,
    ("Turbo/Supercharger", "Pro"): 0x104,
    ("Suspension", "Pro"): 0x105,
    ("Transmission", "Pro"): 0x301,
    ("Nitrous", "Pro"): 0x302,
    ("Suspension", "Super Pro"): 0x303,
    ("Brakes", "Race"): 0x304,
}
MENU_NAMES = {
    0x101: ("Parts", "Body Kits", "Body Style"),
    0x102: ("Parts", "Spoilers", "Spoilers"),
    0x103: ("Parts", "Rims", "Rim Style"),
    0x104: ("Parts", "Hoods", "Hoods"),
    0x105: ("Parts", "Roof Scoops", "Roof Scoops"),
    0x301: ("Visual", "Body Paint", "Body Paint"),
    0x302: ("Visual", "Vinyls", "Vinyls"),
    0x303: ("Visual", "Rim Paint", "Rim Color"),
    0x304: ("Visual", "Window Tint", "Window Tint"),
}
HINT_LOCATION = re.compile(
    r"Performance Shop - [^\n]+? - (?:Turbo/Supercharger|Transmission|Suspension|Nitrous|Engine|Brakes|Tires|Tyres) (?:Super Pro|Ultimate|Race|Pro)(?= in |[).,\n]|$)"
)


def route_shop(row):
    result = dict(row)
    category = str(row.get("category", ""))
    if category == "Tyres":
        category = "Tires"
    tier = str(row.get("tier", ""))
    kind = row.get("location_type")
    if kind == "dealership":
        store = group = menu_name = section = label = "Dealership"
        menu = None
    elif kind in ("visual_shop", "visual_store"):
        store = group = "Visual"
        menu = None
        section = menu_name = category or "Visual"
        label = " ".join(v for v in (category, tier) if v)
    else:
        menu = VISUAL_MENUS.get((category, tier), PERFORMANCE_MENUS.get(category))
        if menu in MENU_NAMES:
            store, menu_name, section = MENU_NAMES[menu]
            group = "Visual"
            label = menu_name
        else:
            store = group = "Performance"
            menu_name = section = category
            label = " ".join(v for v in (category, tier) if v)
    location = str(row.get("location_name", ""))
    display_location = (
        store + " Shop - " + str(row.get("car", "")) + " - " + menu_name
        if group == "Visual"
        else location
    )
    result.update(
        store=store,
        store_group=group,
        store_category=section,
        native_menu=menu,
        native_menu_name=menu_name,
        slot_label=label,
        display_location_name=display_location,
    )
    return result


def visual_categories(rows):
    available = {row["store_category"] for row in rows if row.get("store_group") == "Visual"}
    return [name for name in VISUAL_CATEGORIES if name in available] + sorted(
        available - set(VISUAL_CATEGORIES)
    )


def shop_location_aliases(rows):
    aliases = {}
    for row in rows:
        if row.get("location_type") == "dealership":
            continue
        display = row["display_location_name"]
        legacy = (
            "Performance Shop - "
            + str(row.get("car", ""))
            + " - "
            + str(row.get("category", ""))
            + " "
            + str(row.get("tier", ""))
        )
        if legacy != display:
            aliases[legacy] = display
        if row.get("category") in ("Tires", "Tyres"):
            aliases[
                "Performance Shop - "
                + str(row.get("car", ""))
                + " - Tyres "
                + str(row.get("tier", ""))
            ] = display
        original = row.get("location_name")
        if original and original != display:
            aliases[original] = display
    return aliases


def hint_location(hint, locations, slot_id):
    original = str(hint.get("location_name", ""))
    row = locations.get(hint.get("location"))
    if row and (
        hint.get("finding_player") == slot_id
        or original == row.get("location_name")
        or original in shop_location_aliases([row])
    ):
        return row.get("display_location_name", original)
    return original


def hint_message(record, aliases):
    text = str(record.get("text", ""))
    if record.get("channel") == "StreamLog" and text.startswith("[Hint]"):
        return HINT_LOCATION.sub(lambda match: aliases.get(match.group(0), match.group(0)), text)
    return text
