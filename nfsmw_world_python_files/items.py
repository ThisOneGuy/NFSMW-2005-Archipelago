from .cars import CUSTOMIZABLE_CARS, SPECIAL_CARS
from .performance import PERFORMANCE_PACKAGES

CAR_ITEM_BASE = 1_100_000
PART_ITEM_BASE = 1_200_000
FILLER_ITEM_BASE = 1_900_000
TRAP_ITEM_BASE = 1_950_000

ITEM_TABLE = {}

for car_index, car in enumerate(CUSTOMIZABLE_CARS, 1):
    ITEM_TABLE[car] = {
        "id": CAR_ITEM_BASE + car_index,
        "classification": "progression",
        "type": "car",
        "car": car,
    }

for special_index, car in enumerate(SPECIAL_CARS, 1):
    ITEM_TABLE[car] = {
        "id": CAR_ITEM_BASE + 500 + special_index,
        "classification": "progression",
        "type": "car",
        "car": car,
    }

for car_index, car in enumerate(CUSTOMIZABLE_CARS, 1):
    for part_index, package in enumerate(PERFORMANCE_PACKAGES, 1):
        category = package["category"]
        tier = package["tier"]
        item_name = f"{car} - {category} {tier} Unlock"
        ITEM_TABLE[item_name] = {
            "id": PART_ITEM_BASE + (car_index * 100) + part_index,
            "classification": "useful",
            "type": "performance_part",
            "car": car,
            "category": category,
            "tier": tier,
        }

FILLER_ITEMS = {
    "$5,000 Cash": {
        "id": FILLER_ITEM_BASE + 1,
        "classification": "filler",
        "type": "cash",
        "amount": 5000,
    },
    "$10,000 Cash": {
        "id": FILLER_ITEM_BASE + 2,
        "classification": "filler",
        "type": "cash",
        "amount": 10000,
    },
    "$25,000 Cash": {
        "id": FILLER_ITEM_BASE + 3,
        "classification": "useful",
        "type": "cash",
        "amount": 25000,
    },
}

ITEM_TABLE.update(FILLER_ITEMS)
ITEM_TABLE["Turbo Trap"] = {
    "id": TRAP_ITEM_BASE + 1,
    "classification": "trap",
    "type": "trap",
}

ITEM_TABLE["Brake Trap"] = {
    "id": TRAP_ITEM_BASE + 2,
    "classification": "trap",
    "type": "trap",
}
ITEM_TABLE["Flash Bang Trap"] = {
    "id": TRAP_ITEM_BASE + 3,
    "classification": "trap",
    "type": "trap",
}
ITEM_TABLE["Truck Trap"] = {
    "id": TRAP_ITEM_BASE + 4,
    "classification": "trap",
    "type": "trap",
}
ITEM_TABLE["Speedbreaker Trap"] = {
    "id": TRAP_ITEM_BASE + 5,
    "classification": "trap",
    "type": "trap",
}
TRAP_ITEMS = ("Turbo Trap", "Brake Trap", "Flash Bang Trap", "Truck Trap", "Speedbreaker Trap")

BLACKLIST_UNLOCK_ITEM_BASE = 1_300_000
for rank in range(1, 16):
    ITEM_TABLE[f"Blacklist #{rank} Challenge Permit"] = {
        "id": BLACKLIST_UNLOCK_ITEM_BASE + rank,
        "classification": "progression",
        "type": "blacklist_unlock",
        "blacklist_rank": rank,
    }
