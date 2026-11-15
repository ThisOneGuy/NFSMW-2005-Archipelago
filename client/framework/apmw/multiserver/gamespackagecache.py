import typing as t
from weakref import WeakValueDictionary

from NetUtils import GamesPackage

GameAndChecksum = tuple[str, str | None]
ItemNameGroups = dict[str, list[str]]
LocationNameGroups = dict[str, list[str]]


K = t.TypeVar("K")
V = t.TypeVar("V")


class DictLike(dict[K, V]):
    __slots__ = ("__weakref__",)


class GamesPackageCache:

    _reduced_games_packages: WeakValueDictionary[GameAndChecksum, GamesPackage]
    _item_name_groups: WeakValueDictionary[GameAndChecksum, dict[str, list[str]]]
    _location_name_groups: WeakValueDictionary[GameAndChecksum, dict[str, list[str]]]

    def __init__(self) -> None:
        self._reduced_games_packages = WeakValueDictionary()
        self._item_name_groups = WeakValueDictionary()
        self._location_name_groups = WeakValueDictionary()

    def _get(
        self,
        cache_key: GameAndChecksum,
    ) -> tuple[GamesPackage | None, ItemNameGroups | None, LocationNameGroups | None]:
        if cache_key[1] is None:
            return None, None, None
        return (
            self._reduced_games_packages.get(cache_key, None),
            self._item_name_groups.get(cache_key, None),
            self._location_name_groups.get(cache_key, None),
        )

    def get(
        self,
        game: str,
        full_games_package: GamesPackage,
    ) -> tuple[GamesPackage, ItemNameGroups, LocationNameGroups]:

        cache_key = (game, full_games_package.get("checksum", None))
        cached_reduced_games_package, cached_item_name_groups, cached_location_name_groups = self._get(cache_key)

        if cached_reduced_games_package is None:
            cached_reduced_games_package = t.cast(
                t.Any,
                DictLike(
                    {
                        "item_name_to_id": full_games_package["item_name_to_id"],
                        "location_name_to_id": full_games_package["location_name_to_id"],
                        "checksum": full_games_package.get("checksum", None),
                    }
                ),
            )
            if cache_key[1] is not None:
                self._reduced_games_packages[cache_key] = cached_reduced_games_package

        if cached_item_name_groups is None:

            item_names = {name: name for name in cached_reduced_games_package["item_name_to_id"].keys()}
            cached_item_name_groups = DictLike(
                {
                    group_name: [item_names.get(item_name, item_name) for item_name in group_items]
                    for group_name, group_items in full_games_package["item_name_groups"].items()
                }
            )
            if cache_key[1] is not None:
                self._item_name_groups[cache_key] = cached_item_name_groups

        if cached_location_name_groups is None:

            location_names = {name: name for name in cached_reduced_games_package["location_name_to_id"].keys()}
            cached_location_name_groups = DictLike(
                {
                    group_name: [location_names.get(location_name, location_name) for location_name in group_locations]
                    for group_name, group_locations in full_games_package.get("location_name_groups", {}).items()
                }
            )
            if cache_key[1] is not None:
                self._location_name_groups[cache_key] = cached_location_name_groups

        return cached_reduced_games_package, cached_item_name_groups, cached_location_name_groups

    def get_static(self, game: str) -> tuple[GamesPackage, ItemNameGroups, LocationNameGroups]:

        import worlds

        return self.get(game, worlds.network_data_package["games"][game])
