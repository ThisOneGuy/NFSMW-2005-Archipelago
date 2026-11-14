from .cars import CUSTOMIZABLE_CARS
from .performance import PERFORMANCE_PACKAGES
from .career import BLACKLIST_CAREER
from .client_view.store_routes import route_shop

DEALERSHIP_LOCATION_BASE = 2_100_000
PART_LOCATION_BASE = 2_200_000
RACE_LOCATION_BASE = 2_300_000
MILESTONE_LOCATION_BASE = 2_400_000
RIVAL_LOCATION_BASE = 2_500_000
BLACKLIST_LOCATION_BASE = 2_600_000

LOCATION_TABLE = {}


for car_index, car in enumerate(CUSTOMIZABLE_CARS, 1):
    LOCATION_TABLE[f"Dealership - {car}"] = {
        "id": DEALERSHIP_LOCATION_BASE + car_index,
        "type": "dealership",
        "car": car,
        "base_price": 25000,
        "unlock_condition": f"dealership_slot:{car}",
    }


for car_index, car in enumerate(CUSTOMIZABLE_CARS, 1):
    for part_index, package in enumerate(PERFORMANCE_PACKAGES, 1):
        category = package["category"]
        tier = package["tier"]
        location_name = f"Performance Shop - {car} - {category} {tier}"
        route = route_shop(
            dict(
                location_type="performance_shop",
                car=car,
                category=category,
                tier=tier,
                location_name=location_name,
            )
        )
        name = route["display_location_name"]
        LOCATION_TABLE[name] = {
            "id": PART_LOCATION_BASE + (car_index * 100) + part_index,
            "type": "performance_shop",
            "car": car,
            "category": category,
            "tier": tier,
            "base_price": package["base_price"],
            "unlock_condition": f"performance_slot:{car}:{category}:{tier}",
        }


for rank, stage in BLACKLIST_CAREER.items():
    racer = stage["racer"]

    for event_index, (event_type, route) in enumerate(stage["races"], 1):
        name = f"BL{rank:02d} {racer} - Race - {event_type} - {route}"
        LOCATION_TABLE[name] = {
            "id": RACE_LOCATION_BASE + ((16 - rank) * 100) + event_index,
            "type": "career_race",
            "blacklist_rank": rank,
            "racer": racer,
            "event_type": event_type,
            "route": route,
            "base_price": 5000,
            "unlock_condition": f"win_career_event:{rank}:{event_index}",
        }

    for milestone_index, (milestone_type, target) in enumerate(stage["milestones"], 1):
        name = f"BL{rank:02d} {racer} - Milestone - {milestone_type} - {target}"
        LOCATION_TABLE[name] = {
            "id": MILESTONE_LOCATION_BASE + ((16 - rank) * 100) + milestone_index,
            "type": "milestone",
            "blacklist_rank": rank,
            "racer": racer,
            "milestone_type": milestone_type,
            "target": target,
            "base_price": 5000,
            "unlock_condition": f"complete_milestone:{rank}:{milestone_index}",
        }

    for rival_index, (event_type, route) in enumerate(stage["rival"], 1):
        name = f"BL{rank:02d} {racer} - Rival Race - {event_type} - {route}"
        LOCATION_TABLE[name] = {
            "id": RIVAL_LOCATION_BASE + ((16 - rank) * 100) + rival_index,
            "type": "rival_race",
            "blacklist_rank": rank,
            "racer": racer,
            "event_type": event_type,
            "route": route,
            "base_price": 7500,
            "unlock_condition": f"win_rival_event:{rank}:{rival_index}",
        }

    unlock_name = f"Blacklist #{rank} - {racer} Unlocked"
    defeat_name = f"Blacklist #{rank} - {racer} Defeated"

    LOCATION_TABLE[unlock_name] = {
        "id": BLACKLIST_LOCATION_BASE + ((16 - rank) * 10) + 1,
        "type": "blacklist_unlock",
        "blacklist_rank": rank,
        "racer": racer,
        "base_price": 10000,
        "unlock_condition": f"blacklist_unlocked:{rank}",
    }
    LOCATION_TABLE[defeat_name] = {
        "id": BLACKLIST_LOCATION_BASE + ((16 - rank) * 10) + 2,
        "type": "blacklist_defeat",
        "blacklist_rank": rank,
        "racer": racer,
        "base_price": 15000,
        "unlock_condition": f"blacklist_defeated:{rank}",
    }
