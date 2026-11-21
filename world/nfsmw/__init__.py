from typing import Any, Dict

from BaseClasses import CollectionState, Item, ItemClassification, Location, Region
from worlds.AutoWorld import World

from .cars import CUSTOMIZABLE_CARS, SPECIAL_CARS, logic_cars_for_blacklist
from .items import ITEM_TABLE, FILLER_ITEMS, TRAP_ITEMS
from .locations import LOCATION_TABLE
from .client_view.store_routes import route_shop
from .options import NFSMWOptions
from .event_permits import (
    PROGRESSIVE_EVENT_NAME,
    event_permit_name,
    event_permit_requirement,
)
from .goals import (
    GOAL_FIELDS,
    existing_blacklist_ranks,
    goal_settings,
    goal_completed,
    required_ranks,
    goal_required,
    free_order_blacklist,
)
from .webworld import NFSMWWebWorld

from .client_view.registration import register as _register_client

_register_client()

from .options_creator import register as _register_goal_options

_register_goal_options()


class NFSMWItem(Item):
    game = "Need for Speed: Most Wanted"


class NFSMWLocation(Location):
    game = "Need for Speed: Most Wanted"


CLASSIFICATION_MAP = {
    "progression": ItemClassification.progression,
    "useful": ItemClassification.useful,
    "filler": ItemClassification.filler,
    "trap": ItemClassification.trap,
}


class NFSMWWorld(World):
    game = "Need for Speed: Most Wanted"
    web = NFSMWWebWorld()

    options_dataclass = NFSMWOptions
    options: NFSMWOptions

    item_name_to_id = {name: data["id"] for name, data in ITEM_TABLE.items()}
    location_name_to_id = {name: data["id"] for name, data in LOCATION_TABLE.items()}

    item_name_groups = {
        "Cars": {name for name, data in ITEM_TABLE.items() if data["type"] == "car"},
        "Performance Parts": {
            name
            for name, data in ITEM_TABLE.items()
            if data["type"] == "performance_part"
        },
        "Cash": set(FILLER_ITEMS),
        "Traps": set(TRAP_ITEMS),
        "Rival Challenge Permits": {
            name
            for name, data in ITEM_TABLE.items()
            if data["type"] == "blacklist_unlock"
        },
        "Event Permits": {
            name
            for name, data in ITEM_TABLE.items()
            if data["type"] == "blacklist_event_permit"
        },
    }

    generated_starting_car: str
    generated_blacklist_cars: Dict[int, str]
    generated_opponent_seed: int

    def generate_early(self) -> None:
        self.event_permits = self.options.blacklist_event_permits.current_key
        self.goal_mode = self.options.goal.current_key
        if self.goal_mode == "blacklist_count":
            self.options.blacklist_exist_count.value = max(
                self.options.blacklist_exist_count.value,
                self.options.goal_blacklist_count.value,
            )
        self.goal_data = goal_settings(
            {
                "goal": self.goal_mode,
                "blacklist_exist_count": self.options.blacklist_exist_count.value,
                **{
                    name: getattr(self.options, name).value
                    for name in GOAL_FIELDS[self.goal_mode]
                },
            }
        )
        self.blacklist_ranks = existing_blacklist_ranks(self.goal_data)
        if self.goal_mode == "specific_blacklist" and not required_ranks(
            self.goal_data
        ).issubset(self.blacklist_ranks):
            raise ValueError(
                "goal_blacklist targets a member excluded by blacklist_exist_count. Choose an included rival or include more Blacklist members."
            )
        self.free_order_blacklist = free_order_blacklist(
            {
                **self.goal_data,
                "randomize_blacklist_unlocks": bool(
                    self.options.randomize_blacklist_unlocks
                ),
            }
        )
        if self.options.randomize_blacklist_unlocks or self.event_permits != "disabled":
            self.options.accessibility.value = self.options.accessibility.option_full
        if self.options.randomize_blacklist_unlocks and self.multiworld.players > 1:
            self.options.non_local_items.value.update(
                f"Blacklist #{rank} Rival Challenge Permit"
                for rank in self.blacklist_ranks
            )
        if self.options.starting_car.value == 1:
            starter_pool = [
                "Fiat Punto",
                "Chevrolet Cobalt SS",
                "Lexus IS 300",
                "Volkswagen Golf GTI",
            ]
            self.generated_first_car = self.random.choice(starter_pool)
        else:
            self.generated_first_car = self.random.choice(CUSTOMIZABLE_CARS)
        count = (
            self.options.shop_car_count.value
            if self.options.shuffle_performance_parts or self.options.visual_store_checks
            else 0
        )
        if count == len(CUSTOMIZABLE_CARS):
            self.shop_cars = tuple(CUSTOMIZABLE_CARS)
        elif count:
            selected = {self.generated_first_car}
            selected.update(
                self.random.sample(
                    [car for car in CUSTOMIZABLE_CARS if car not in selected], count - 1
                )
            )
            self.shop_cars = tuple(car for car in CUSTOMIZABLE_CARS if car in selected)
        else:
            self.shop_cars = ()
        self.active_locations = {}
        for name, data in LOCATION_TABLE.items():
            rank = data.get("blacklist_rank", 0)
            if rank and rank not in self.blacklist_ranks:
                continue
            if data["type"] == "performance_shop":
                if data["car"] not in self.shop_cars:
                    continue
                visual = (
                    route_shop(
                        dict(data, location_type=data["type"], location_name=name)
                    )["store_group"]
                    == "Visual"
                )
                if visual and not self.options.visual_store_checks:
                    continue
                if not visual and not self.options.shuffle_performance_parts:
                    continue
            self.active_locations[name] = data
        self.generated_starting_car = ""
        self.first_car_location = "Dealership - Aston Martin DB9"

        if self.options.randomize_blacklist_cars:
            chosen = self.random.sample(CUSTOMIZABLE_CARS, len(self.blacklist_ranks))
            self.generated_blacklist_cars = {
                rank: car
                for rank, car in zip(sorted(self.blacklist_ranks, reverse=True), chosen)
            }
        else:
            self.generated_blacklist_cars = {}
        self.generated_opponent_seed = self.random.randrange(0, 2**31)

    def create_regions(self) -> None:
        menu = Region("Menu", self.player, self.multiworld)
        rockport = Region("Rockport Career", self.player, self.multiworld)
        dealership = Region("AP Dealership", self.player, self.multiworld)
        performance = Region("AP Performance Shop", self.player, self.multiworld)
        self.multiworld.regions += [menu, rockport, dealership, performance]
        menu.connect(rockport)
        menu.connect(dealership)
        menu.connect(performance)
        for name, data in self.active_locations.items():
            region = (
                dealership
                if data["type"] == "dealership"
                else performance if data["type"] == "performance_shop" else rockport
            )
            region.locations.append(
                NFSMWLocation(self.player, name, data["id"], region)
            )
        goal = NFSMWLocation(self.player, "Career Goal", None, rockport)
        goal.place_locked_item(
            NFSMWItem("Victory", ItemClassification.progression, None, self.player)
        )
        rockport.locations.append(goal)

    def create_item(self, name: str) -> NFSMWItem:
        data = ITEM_TABLE[name]
        return NFSMWItem(
            name,
            CLASSIFICATION_MAP[data["classification"]],
            data["id"],
            self.player,
        )

    def create_items(self) -> None:
        core_names = [
            name for name, data in ITEM_TABLE.items() if data["type"] == "car"
        ]
        if self.options.randomize_blacklist_unlocks:
            core_names += [
                f"Blacklist #{rank} Rival Challenge Permit"
                for rank in sorted(self.blacklist_ranks)
            ]
        if self.event_permits == "individual":
            core_names += [
                event_permit_name(rank) for rank in sorted(self.blacklist_ranks - {15})
            ]
        elif self.event_permits == "progressive":
            core_names += [PROGRESSIVE_EVENT_NAME] * (len(self.blacklist_ranks) - 1)
        first = self.multiworld.get_location(self.first_car_location, self.player)
        first.place_locked_item(self.create_item(self.generated_first_car))
        core_names.remove(self.generated_first_car)
        total_locations = len(self.active_locations) - 1
        if len(core_names) > total_locations:
            raise ValueError(
                "The selected location set does not have enough space for progression items."
            )
        if self.options.shuffle_performance_parts:
            upgrades = [
                name
                for name, data in ITEM_TABLE.items()
                if data["type"] == "performance_part" and data["car"] in self.shop_cars
            ]
            available = total_locations - len(core_names)
            core_names += (
                upgrades
                if len(upgrades) <= available
                else self.random.sample(upgrades, available)
            )
        pool = [self.create_item(name) for name in core_names]
        traps = self.enabled_trap_items()
        trap_count = (
            (total_locations - len(pool)) * self.options.trap_percentage.value // 100
            if traps
            else 0
        )
        pool.extend(
            self.create_item(self.random.choice(traps)) for _ in range(trap_count)
        )
        while len(pool) < total_locations:
            pool.append(self.create_item(self.random.choice(tuple(FILLER_ITEMS))))
        self.multiworld.itempool += pool

    def enabled_trap_items(self):
        if self.options.trap_percentage.value <= 0:
            return ()
        return tuple(
            name for name in TRAP_ITEMS if name not in self.options.excluded_traps.value
        )

    def get_filler_item_name(self) -> str:
        traps = self.enabled_trap_items()
        if traps and self.random.randrange(100) < self.options.trap_percentage.value:
            return self.random.choice(traps)
        return self.random.choice(tuple(FILLER_ITEMS))

    def set_rules(self) -> None:
        player = self.player
        cars = tuple(CUSTOMIZABLE_CARS + SPECIAL_CARS)
        defeats = {
            data["blacklist_rank"]: name
            for name, data in self.active_locations.items()
            if data["type"] == "blacklist_defeat"
        }
        for name, data in self.active_locations.items():
            rank = data.get("blacklist_rank", 0)
            location = self.multiworld.get_location(name, player)
            permits = ()
            forbidden = set()
            if rank and self.options.randomize_blacklist_unlocks:
                forbidden.add(f"Blacklist #{rank} Rival Challenge Permit")
            kind = data["type"]
            event_locked = bool(
                rank
                and kind not in ("dealership", "performance_shop")
                and (
                    kind != "blacklist_unlock"
                    or not self.options.randomize_blacklist_unlocks
                )
            )
            requirement = (
                event_permit_requirement(self.event_permits, rank)
                if event_locked
                else None
            )
            if requirement and self.event_permits == "individual":
                forbidden.add(requirement[0])
            if forbidden:
                previous = location.item_rule
                location.item_rule = lambda item, old=previous, keys=frozenset(
                    forbidden
                ): old(item) and not (item.game == self.game and item.name in keys)
            if (
                rank
                and data["type"]
                in ("blacklist_unlock", "blacklist_defeat", "rival_race")
                and self.options.randomize_blacklist_unlocks
            ):
                permits += (f"Blacklist #{rank} Rival Challenge Permit",)
            if data["type"] == "performance_shop":
                self.multiworld.get_location(name, player).access_rule = (
                    lambda state, p=player, car=data["car"]: state.has(car, p)
                )
            elif data["type"] != "dealership":
                eligible = (
                    logic_cars_for_blacklist(rank)
                    if rank and kind != "blacklist_unlock"
                    else cars
                )
                predecessor = (
                    defeats[rank + 1]
                    if rank
                    and rank < 15
                    and self.event_permits != "disabled"
                    and not self.free_order_blacklist
                    and kind in ("blacklist_unlock", "blacklist_defeat", "rival_race")
                    else None
                )
                location.access_rule = (
                    lambda state, p=player, names=eligible, keys=permits, event=requirement, previous=predecessor: state.has_any(
                        names, p
                    )
                    and state.has_all(keys, p)
                    and (event is None or state.has(event[0], p, event[1]))
                    and (previous is None or state.can_reach(previous, "Location", p))
                )
        self.multiworld.get_location(self.first_car_location, player).access_rule = (
            lambda state: True
        )
        self.set_completion_rules()

    @classmethod
    def stage_post_fill(cls, multiworld):
        worlds = [
            world
            for world in multiworld.worlds.values()
            if isinstance(world, cls) and world.player in multiworld.player_ids
        ]
        if not worlds:
            return
        for world in worlds:
            for name, data in world.active_locations.items():
                rank = data.get("blacklist_rank", 0)
                if not rank:
                    continue
                location = multiworld.get_location(name, world.player)
                item = location.item
                if (
                    world.options.randomize_blacklist_unlocks
                    and item
                    and item.game == cls.game
                    and item.name == f"Blacklist #{rank} Rival Challenge Permit"
                ):
                    raise ValueError(
                        f"Blacklist #{rank} unlock cannot be placed in that rival's rewards: {location}."
                    )
        state = CollectionState(multiworld)
        remaining = set(multiworld.get_filled_locations())
        while remaining:
            reachable = {
                location for location in remaining if location.can_reach(state)
            }
            if not reachable:
                break
            for location in reachable:
                state.collect(location.item, True, location)
            remaining.difference_update(reachable)
        for world in worlds:
            missing = [
                str(rank)
                for rank in sorted(world.blacklist_ranks)
                if world.options.randomize_blacklist_unlocks
                and not state.has(
                    f"Blacklist #{rank} Rival Challenge Permit", world.player
                )
            ]
            if world.event_permits == "individual":
                missing += [
                    f"event {rank}"
                    for rank in sorted(world.blacklist_ranks - {15})
                    if not state.has(event_permit_name(rank), world.player)
                ]
            elif (
                world.event_permits == "progressive"
                and len(world.blacklist_ranks) > 1
                and not state.has(
                    PROGRESSIVE_EVENT_NAME, world.player, len(world.blacklist_ranks) - 1
                )
            ):
                missing.append("progressive events")
            if missing:
                raise ValueError(
                    f"Unreachable Blacklist permits for player {world.player}: {', '.join(missing)}. The seed was rejected to prevent a progression lock."
                )
            if not multiworld.completion_condition[world.player](state):
                raise ValueError(
                    f"The NFSMW goal for player {world.player} is unreachable. The seed was rejected to prevent a progression lock."
                )

    @classmethod
    def stage_pre_output(cls, multiworld):
        cls.stage_post_fill(multiworld)

    def set_completion_rules(self) -> None:
        rivals = tuple(
            (data["blacklist_rank"], name)
            for name, data in self.active_locations.items()
            if data["type"] == "blacklist_defeat"
        )
        settings = dict(self.goal_data)

        def can_finish(state):
            reachable = {
                rank
                for rank, name in rivals
                if state.can_reach(name, "Location", self.player)
            }
            return goal_completed(
                settings,
                reachable,
                (
                    required_ranks(settings).issubset(reachable)
                    if settings["goal"] == "final_escape"
                    else False
                ),
            )

        self.multiworld.get_location("Career Goal", self.player).access_rule = (
            can_finish
        )
        self.multiworld.completion_condition[self.player] = lambda state: state.has(
            "Victory", self.player
        )

    def fill_slot_data(self) -> Dict[str, Any]:
        return {
            "schema_version": 7,
            **self.goal_data,
            "shop_car_count": self.options.shop_car_count.value,
            "shop_cars": list(self.shop_cars),
            "shuffle_performance_parts": bool(self.options.shuffle_performance_parts),
            "visual_store_checks": bool(self.options.visual_store_checks),
            "reveal_event_rewards": bool(self.options.reveal_event_rewards),
            "excluded_traps": sorted(self.options.excluded_traps.value),
            "enabled_traps": list(self.enabled_trap_items()),
            "randomize_blacklist_unlocks": bool(
                self.options.randomize_blacklist_unlocks
            ),
            "blacklist_event_permits": self.event_permits,
            "blacklist_logic_cars": {
                str(rank): list(logic_cars_for_blacklist(rank))
                for rank in sorted(self.blacklist_ranks)
            },
            "blacklist_unlock_placement": (
                "other_players"
                if self.options.randomize_blacklist_unlocks
                and self.multiworld.players > 1
                else (
                    "own_world"
                    if self.options.randomize_blacklist_unlocks
                    else "disabled"
                )
            ),
            "open_world": self.free_order_blacklist or self.event_permits != "disabled",
            "blacklist_order": "any" if self.free_order_blacklist else "career",
            "included_blacklist_ranks": sorted(self.blacklist_ranks),
            "active_location_ids": [
                data["id"] for data in self.active_locations.values()
            ],
            "bounty_mode": self.options.bounty_mode.current_key,
            "bounty_multiplier": float(self.options.bounty_multiplier.value),
            "bounty_multiplier_applies_to": "earned",
            "trap_percentage": self.options.trap_percentage.value,
            "turbo_trap_boost_start_ms": 2000,
            "turbo_trap_end_ms": 17000,
            "brake_trap_duration_ms": 3000,
            "flash_bang_start_ms": 1000,
            "flash_bang_end_ms": 6316,
            "flash_bang_fade_ms": 500,
            "truck_trap_cue_ms": 5000,
            "truck_trap_end_ms": 6316,
            "required_blacklist_ranks": sorted(required_ranks(self.goal_data)),
            "required_blacklist_count": (
                len(self.blacklist_ranks)
                if self.goal_mode == "final_escape"
                else goal_required(self.goal_data)
            ),
            "dealership_first_start": True,
            "first_car_purchase_in_store": True,
            "first_car_location_id": LOCATION_TABLE[self.first_car_location]["id"],
            "first_car_item_id": ITEM_TABLE[self.generated_first_car]["id"],
            "first_car": self.generated_first_car,
            "first_car_price": 0,
            "starting_car": self.generated_starting_car,
            "blacklist_cars": self.generated_blacklist_cars,
            "randomize_opponent_cars": bool(self.options.randomize_opponent_cars.value),
            "opponent_car_seed": self.generated_opponent_seed,
            "randomize_blacklist_appearance": bool(
                self.options.randomize_blacklist_cars
            ),
            "blacklist_appearance_seed": self.generated_opponent_seed,
            "shop_price_multiplier": self.options.shop_price_multiplier.value / 100.0,
            "death_link": bool(self.options.death_link.value),
            "location_count": len(self.active_locations),
        }
