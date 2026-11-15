from functools import wraps
from pathlib import Path
import sys
from .goals import GOAL_FIELDS

GAME = "Need for Speed: Most Wanted"
FIELDS = ("goal_blacklist_count", "goal_blacklist")


def visible_goal_fields(value):
    if type(value) is int and 0 <= value <= 2:
        value = tuple(GOAL_FIELDS)[value]
    if isinstance(value, str) and (value == "random" or value.startswith("random-")):
        return FIELDS
    return GOAL_FIELDS.get(value, ()) if isinstance(value, str) else ()


def export_goal_options(values):
    result = dict(values)
    active = visible_goal_fields(result.get("goal", "blacklist_count"))
    for name in FIELDS:
        if name not in active:
            result.pop(name, None)
    return result


class GoalValues(dict):
    def __init__(self, values, changed):
        super().__init__(values)
        self.changed = changed

    def __setitem__(self, name, value):
        super().__setitem__(name, value)
        if name == "goal":
            self.changed()


def refresh_goal_fields(app):
    active = visible_goal_fields(app.options.get("goal", "blacklist_count"))
    for parent, order in getattr(app, "_nfsmw_goal_order", ()):
        for name, row in app._nfsmw_goal_rows.items():
            if row not in order:
                continue
            shown = name in active
            if not shown and row.parent is parent:
                for child in row.walk(restrict=True):
                    if hasattr(child, "focus"):
                        child.focus = False
                parent.remove_widget(row)
            elif shown and row.parent is None:
                index = sum(child.parent is parent for child in order[order.index(row) + 1 :])
                parent.add_widget(row, index=index)


def install(creator):
    if getattr(creator, "_nfsmw_goal_visibility", False):
        return
    create_option = creator.create_option
    create_panel = creator.create_options_panel
    export_options = creator.export_options

    @wraps(create_option)
    def option(self, definition, name, world):
        row = create_option(self, definition, name, world)
        if world.game == GAME and name in FIELDS and hasattr(self, "_nfsmw_goal_rows"):
            self._nfsmw_goal_rows[name] = row
        return row

    @wraps(create_panel)
    def panel(self, world_button):
        self._nfsmw_goal_rows = {}
        self._nfsmw_goal_order = ()
        if world_button.world_cls.game == GAME:
            self.options = GoalValues(self.options, lambda: refresh_goal_fields(self))
        elif isinstance(self.options, GoalValues):
            self.options = dict(self.options)
        result = create_panel(self, world_button)
        if world_button.world_cls.game == GAME:
            parents = {
                row.parent for row in self._nfsmw_goal_rows.values() if row.parent is not None
            }
            self._nfsmw_goal_order = tuple(
                (parent, tuple(reversed(parent.children))) for parent in parents
            )
            refresh_goal_fields(self)
        return result

    @wraps(export_options)
    def export(self, *args, **kwargs):
        if self.current_game != GAME:
            return export_options(self, *args, **kwargs)
        values = self.options
        self.options = export_goal_options(values)
        try:
            return export_options(self, *args, **kwargs)
        finally:
            self.options = values

    creator.create_option = option
    creator.create_options_panel = panel
    creator.export_options = export
    creator._nfsmw_goal_visibility = True


def register():
    module = sys.modules.get("OptionsCreator")
    if module is None:
        for name in ("__main__", "__mp_main__"):
            candidate = sys.modules.get(name)
            if candidate and Path(getattr(candidate, "__file__", "")).stem in (
                "OptionsCreator",
                "ArchipelagoOptionsCreator",
            ):
                module = candidate
                break
    if module is None:
        return
    creator = getattr(module, "OptionsCreator", None)
    if creator is not None:
        install(creator)
        return
    from kivy.clock import Clock

    def ready(_):
        creator = getattr(module, "OptionsCreator", None)
        if creator is not None:
            install(creator)

    Clock.schedule_once(ready, 0)
