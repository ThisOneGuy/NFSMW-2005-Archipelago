from __future__ import annotations
import json
import queue
from math import ceil
from contextlib import ExitStack
from importlib.resources import files, as_file
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.core.text.markup import MarkupLabel as CoreMarkupLabel
from kivy.graphics import Color, Rectangle, Line, Ellipse
from kivy.metrics import dp
from kivy.effects.scroll import ScrollEffect
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.utils import get_color_from_hex, escape_markup
from .catalog import blank_snapshot
from .connection_links import parse_link, from_fields, ConnectionLink
from .ipc import ViewWorker
from .store_routes import (
    route_shop,
    visual_categories,
    hint_location,
    hint_message,
    shop_location_aliases,
)
from .hint_search import normalized, matching_names, filter_hints

BG = "#000e25"
PANEL = "#001f44"
TAB_BG = "#001939"
SELECTED = "#005db6"
BLUE = "#65b3ff"
WHITE = "#ffffff"
FIELD = "#000e25"
BORDER = "#415374"
DIM = "#91a6bf"
GREEN = "#69de8b"
PURPLE = "#bf92ff"
GOLD = "#f3cf58"
TEAL = "#63d4da"
LOG_FONT = "Roboto"
LOG_LINE_HEIGHT = 1.1
ROUTINE_LOG_PREFIXES = (
    "READ-ONLY NFSMW save-rank probe",
    "Save-rank probe found",
    "AP isolated save rank changed:",
)


def rgba(value):
    return get_color_from_hex(value)


def is_routine_client_message(record):
    return (
        record.get("channel") == "NFSMW"
        and record.get("level") in ("DEBUG", "INFO")
        and str(record.get("text", "")).startswith(ROUTINE_LOG_PREFIXES)
    )


class Surface(BoxLayout):
    def __init__(self, color=BG, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*rgba(color))
            self.fill = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self.sync, size=self.sync)

    def sync(self, *_):
        self.fill.pos = self.pos
        self.fill.size = self.size


class RivalLockIcon(Widget):
    def __init__(self, locked=True, **kw):
        super().__init__(**kw)
        self.locked = locked
        self.bind(pos=self.draw, size=self.draw)
        self.draw()

    def draw(self, *_):
        self.canvas.clear()
        if not self.locked:
            return
        x, y = self.x + self.width * 0.18, self.y + self.height * 0.15
        w, h = self.width * 0.64, self.height * 0.43
        with self.canvas:
            Color(*rgba(GOLD))
            Line(
                rounded_rectangle=(x + w * 0.2, y + h * 0.75, w * 0.6, h * 0.95, dp(3)),
                width=dp(1.4),
            )
            Rectangle(pos=(x, y), size=(w, h))
            Color(*rgba(BG))
            Ellipse(pos=(x + w * 0.4, y + h * 0.45), size=(w * 0.2, w * 0.2))
            Rectangle(pos=(x + w * 0.45, y + h * 0.25), size=(w * 0.1, h * 0.35))


class Entry(TextInput):
    def __init__(self, **kw):
        super().__init__(
            multiline=False,
            font_size=dp(16),
            foreground_color=rgba(BLUE),
            cursor_color=rgba(BLUE),
            background_color=rgba(FIELD),
            background_normal="",
            background_active="",
            padding=(dp(8), dp(7)),
            write_tab=False,
            **kw,
        )
        with self.canvas.after:
            Color(*rgba(BORDER))
            self.edge = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, dp(4)), width=1
            )
        self.bind(pos=self.sync, size=self.sync)
        self.sync()

    def sync(self, *_):
        self.edge.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(4))


class HintEntry(Entry):
    def keyboard_on_key_down(self, window, keycode, text, modifiers):
        app = App.get_running_app()
        if keycode[1] in ("up", "down") and app.move_hint_selection(
            -1 if keycode[1] == "up" else 1
        ):
            return True
        if keycode[1] == "escape" and app.hint_choices:
            app.close_hint_choices()
            return True
        return super().keyboard_on_key_down(window, keycode, text, modifiers)


class ClearScroll(ScrollView):
    def __init__(self, **kw):
        kw.setdefault("bar_width", dp(14))
        kw.setdefault("scroll_type", ["bars", "content"])
        kw.setdefault("bar_color", rgba(BLUE))
        kw.setdefault("bar_inactive_color", rgba(BORDER))
        kw.setdefault("effect_cls", ScrollEffect)
        kw.setdefault("scroll_wheel_distance", dp(48))
        super().__init__(**kw)


class Info(Label):
    def __init__(self, **kw):
        super().__init__(
            text="i",
            bold=True,
            font_size=dp(16),
            color=rgba(BG),
            size_hint_x=None,
            width=dp(20),
            **kw,
        )
        with self.canvas.before:
            Color(*rgba(BLUE))
            self.circle = Ellipse(size=(dp(20), dp(20)))
        self.bind(pos=self.sync, size=self.sync)

    def sync(self, *_):
        self.circle.pos = (self.center_x - dp(10), self.center_y - dp(10))


def label(text="", color=BLUE, size=16, **kw):
    result = Label(
        text=text, color=rgba(color), font_size=dp(size), halign="left", valign="middle", **kw
    )
    result.bind(size=lambda w, s: setattr(w, "text_size", (max(1, s[0]), s[1])))
    return result


def button(text, callback, **kw):
    result = Button(
        text=text,
        font_size=dp(14),
        background_normal="",
        background_down="",
        background_color=rgba(BLUE),
        color=rgba("#002a50"),
        **kw,
    )
    result.bind(on_release=lambda *_: callback())
    return result


class LogRow(RecycleDataViewBehavior, Label):
    def __init__(self, **kw):
        super().__init__(
            markup=True,
            font_name=LOG_FONT,
            font_size=dp(20),
            line_height=LOG_LINE_HEIGHT,
            color=rgba(WHITE),
            halign="left",
            valign="top",
            padding=(dp(2), dp(2)),
            **kw,
        )
        self.bind(width=lambda w, v: setattr(w, "text_size", (max(1, v - dp(4)), None)))


class ClientApp(App):
    title = "Archipelago NFSMW Client 1.0.1"

    def __init__(self, initial_url=None, worker=None, start_worker=True, **kw):
        super().__init__(**kw)
        self.worker = worker or ViewWorker()
        self.start_worker = start_worker
        self.current = blank_snapshot()
        self.live = False
        self.active = "Archipelago"
        self.closed = False
        self.selected_car = self.current["cars"][0]["name"]
        self.category = ""
        self.expanded = set()
        self.visual_expanded = set()
        self.locations = {}
        self.location_aliases = {}
        self.car_signature = None
        self.part_signature = None
        self.hint_signature = None
        self.text_session = None
        self.text_sequence = 0
        self.text_records = []
        self.pending_link = None
        self.link_display = None
        self.link_attempted = None
        self.link_error = ""
        self.connection_dialog = None
        self.connection_fields = {}
        self.connection_notice = None
        self.connection_in_flight = False
        self.credentials_sent = None
        self.selected_part = None
        self.hint_names = ()
        self.hint_choices = []
        self.hint_index = -1
        self.hint_choice = ""
        self.hint_match_signature = None
        self.hint_session = None
        self.hint_request_pending = False
        self.hint_waiting_item = None
        self.hint_request_sequence = 0
        self.resource_stack = ExitStack()
        self.icon = str(
            self.resource_stack.enter_context(
                as_file(files(__package__).joinpath("assets/archipelago.png"))
            )
        )
        if initial_url:
            try:
                self.pending_link = parse_link(initial_url)
                self.link_display = ConnectionLink(self.pending_link.server, self.pending_link.slot)
            except ValueError as exc:
                self.link_error = str(exc)

    def build(self):
        Window.clearcolor = rgba(BG)
        Window.minimum_width = 800
        Window.minimum_height = 600
        root = Surface(orientation="vertical", spacing=dp(2))
        top = Surface(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            padding=(dp(6), dp(4)),
            spacing=dp(5),
        )
        top.add_widget(Info())
        top.add_widget(label("Server:", size_hint_x=None, width=dp(50)))
        self.server = Entry(hint_text="Server address, e.g. archipelago.gg:38281")
        self.server.bind(on_text_validate=lambda *_: self.connect_clicked())
        top.add_widget(self.server)
        self.connect_button = button(
            "Connect", self.connect_clicked, size_hint_x=None, width=dp(100)
        )
        top.add_widget(self.connect_button)
        root.add_widget(top)
        tabs = Surface(orientation="horizontal", size_hint_y=None, height=dp(42))
        self.tab_buttons = {}
        for name in ("Archipelago", "Hints", "Cars & Parts", "Blacklist"):
            item = button(name, lambda name=name: self.select_tab(name))
            tabs.add_widget(item)
            self.tab_buttons[name] = item
        root.add_widget(tabs)
        self.body = Surface(orientation="vertical")
        root.add_widget(self.body)
        self.pages = {
            "Archipelago": self.build_log(),
            "Hints": self.build_hints(),
            "Cars & Parts": self.build_cars(),
            "Blacklist": self.build_blacklist(),
        }
        command = Surface(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(39),
            padding=(dp(6), dp(3)),
            spacing=dp(5),
        )
        command.add_widget(button("Command:", self.send, size_hint_x=None, width=dp(115)))
        self.command = Entry()
        self.command.bind(on_text_validate=lambda *_: self.send())
        command.add_widget(self.command)
        root.add_widget(command)
        self.select_tab("Archipelago")
        self.render(self.current)
        if self.link_display:
            self.server.text = self.link_display.server
        if self.link_error:
            self.set_notice(self.link_error)
        elif self.pending_link:
            self.set_notice("Connection client is not running.")
        if self.start_worker:
            self.worker.start()
            Clock.schedule_interval(self.poll, 0.1)
        return root

    def select_tab(self, name):
        if name != "Hints" and hasattr(self, "new_hint"):
            self.new_hint.focus = False
            self.hint_filter.focus = False
        self.active = name
        self.body.clear_widgets()
        self.body.add_widget(self.pages[name])
        for key, item in self.tab_buttons.items():
            item.background_color = rgba(SELECTED if key == name else TAB_BG)
            item.color = rgba(DIM if key == name else WHITE)

    def build_log(self):
        page = Surface(orientation="vertical", color="#000000")
        self.log_scroll = RecycleView(
            do_scroll_x=False,
            scroll_y=0,
            bar_width=dp(14),
            scroll_type=["bars", "content"],
            effect_cls=ScrollEffect,
            bar_color=rgba(BLUE),
            bar_inactive_color=rgba(BORDER),
        )
        layout = RecycleBoxLayout(
            default_size=(None, dp(30)),
            key_size="size",
            default_size_hint=(1, None),
            size_hint_y=None,
            orientation="vertical",
            padding=(dp(4), dp(4), dp(20), dp(4)),
        )
        layout.bind(minimum_height=layout.setter("height"))
        self.log_scroll.add_widget(layout)
        self.log_scroll.viewclass = LogRow
        self._log_reflow = Clock.create_trigger(self.reflow_log, 0)
        self._log_follow = Clock.create_trigger(self.follow_log, 0)
        self.log_scroll.bind(width=self._log_reflow)
        page.add_widget(self.log_scroll)
        self.status = label(
            "Connection client is not running.", WHITE, 18, size_hint_y=None, height=dp(48)
        )
        page.add_widget(self.status)
        return page

    def build_hints(self):
        page = Surface(orientation="vertical", spacing=dp(3))
        self.hint_filter = Entry(
            hint_text="Search shared hints by item, player, or location",
            size_hint_y=None,
            height=dp(36),
        )
        self.hint_filter.bind(text=lambda *_: self.filter_shared_hints())
        page.add_widget(self.hint_filter)
        self.hint_summary = label(size=14, size_hint_y=None, height=dp(24))
        page.add_widget(self.hint_summary)
        headers = Surface(color=PANEL, size_hint_y=None, height=dp(57), padding=(dp(3), 0))
        columns = [
            ("Receiving\nPlayer", 0.18),
            ("Item", 0.15),
            ("Finding Player", 0.20),
            ("Location", 0.16),
            ("Entrance", 0.17),
            ("Status", 0.14),
        ]
        for name, width in columns:
            item = label("[u]" + name + "[/u]", size=20, size_hint_x=width, markup=True)
            item.halign = "center"
            headers.add_widget(item)
        page.add_widget(headers)
        scroll = ClearScroll(do_scroll_x=False)
        self.hints_scroll = scroll
        self.hint_rows = GridLayout(cols=1, size_hint_y=None)
        self.hint_rows.bind(minimum_height=self.hint_rows.setter("height"))
        scroll.add_widget(self.hint_rows)
        page.add_widget(scroll)
        self.hint_notice = label(
            "Hints requested or revealed by anyone in this room.",
            DIM,
            14,
            size_hint_y=None,
            height=dp(40),
        )
        page.add_widget(self.hint_notice)
        self.hint_matches_scroll = ClearScroll(do_scroll_x=False, size_hint_y=None, height=0)
        self.hint_matches = GridLayout(cols=1, size_hint_y=None)
        self.hint_matches.bind(minimum_height=self.hint_matches.setter("height"))
        self.hint_matches_scroll.add_widget(self.hint_matches)
        page.add_widget(self.hint_matches_scroll)
        row = Surface(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
        row.add_widget(label("New Hint:", size_hint_x=None, width=dp(74)))
        self.new_hint = HintEntry(hint_text="Type an item name to see matches")
        self.new_hint.bind(
            text=lambda *_: self.update_hint_matches(),
            on_text_validate=lambda *_: self.request_hint(),
        )
        row.add_widget(self.new_hint)
        self.hint_button = button(
            "Request hint", self.request_hint, size_hint_x=None, width=dp(120)
        )
        row.add_widget(self.hint_button)
        page.add_widget(row)
        return page

    def build_cars(self):
        page = Surface(orientation="vertical", padding=dp(8), spacing=dp(6))
        self.summary = label(size_hint_y=None, height=dp(27))
        page.add_widget(self.summary)
        self.search = Entry(hint_text="Search cars, parts, rewards, or players")
        self.search.size_hint_y = None
        self.search.height = dp(35)
        self.search.bind(text=lambda *_: self.filter_cars())
        page.add_widget(self.search)
        columns = Surface(orientation="horizontal", spacing=dp(10))
        page.add_widget(columns)
        left = ClearScroll(size_hint_x=None, width=dp(230), do_scroll_x=False)
        self.cars_scroll = left
        self.car_rows = GridLayout(cols=1, size_hint_y=None)
        self.car_rows.bind(minimum_height=self.car_rows.setter("height"))
        left.add_widget(self.car_rows)
        columns.add_widget(left)
        right = Surface(orientation="vertical", spacing=dp(5))
        columns.add_widget(right)
        self.car_heading = label(size=18, size_hint_y=None, height=dp(28))
        right.add_widget(self.car_heading)
        scroll = ClearScroll(do_scroll_x=True, do_scroll_y=True)
        self.parts_scroll = scroll
        self.part_rows = GridLayout(cols=1, size_hint=(None, None), width=dp(1140))
        self.part_rows.bind(minimum_height=self.part_rows.setter("height"))
        scroll.add_widget(self.part_rows)
        right.add_widget(scroll)
        self.detail = label("", WHITE, 15, size_hint_y=None, height=dp(54))
        right.add_widget(self.detail)
        controls = Surface(size_hint_y=None, height=dp(32), spacing=dp(10))
        self.reveal_button = button(
            "Reveal hint", self.reveal_selected, size_hint_x=None, width=dp(120)
        )
        self.reveal_button.disabled = True
        controls.add_widget(self.reveal_button)
        for text, color in [
            ("Received", GREEN),
            ("Checked", TEAL),
            ("Hinted", PURPLE),
            ("Progression", GOLD),
            ("Available", BLUE),
        ]:
            controls.add_widget(label(text, color, 13))
        page.add_widget(controls)
        return page

    def build_blacklist(self):
        page = Surface(orientation="vertical", padding=dp(8), spacing=dp(6))
        self.blacklist_notice = label("", WHITE, 15, size_hint_y=None, height=dp(65))
        page.add_widget(self.blacklist_notice)
        scroll = ClearScroll(do_scroll_x=False)
        self.blacklist_rows = GridLayout(cols=1, size_hint_y=None, spacing=dp(5))
        self.blacklist_rows.bind(minimum_height=self.blacklist_rows.setter("height"))
        scroll.add_widget(self.blacklist_rows)
        page.add_widget(scroll)
        return page

    def render_blacklist(self, data):
        enabled = bool(data.get("blacklist_randomized"))
        self.tab_buttons["Blacklist"].disabled = not enabled
        if not enabled and self.active == "Blacklist":
            self.select_tab("Archipelago")
        rows = data.get("blacklist", [])
        signature = (enabled, data.get("connected"), json.dumps(rows, sort_keys=True))
        if signature == getattr(self, "blacklist_signature", None):
            return
        self.blacklist_signature = signature
        self.blacklist_rows.clear_widgets()
        self.blacklist_notice.text = (
            "Receive a rival's Challenge Permit, meet their race, milestone and bounty requirements, then select them in the game's Blacklist menu."
            if enabled
            else "This seed does not use Blacklist unlock items."
        )
        if not enabled:
            return
        for row in rows:
            unlocked = bool(row.get("unlocked"))
            defeated = bool(row.get("defeated"))
            line = Surface(orientation="horizontal", size_hint_y=None, height=dp(38), spacing=dp(8))
            line.add_widget(
                RivalLockIcon(
                    locked=not unlocked,
                    size_hint=(None, None),
                    size=(dp(22), dp(30)),
                    pos_hint={"center_y": 0.5},
                )
            )
            line.add_widget(label("#" + str(row["rank"]) + "  " + row["name"], WHITE, 16))
            text = (
                "Defeated"
                if defeated and unlocked
                else "Unlock received" if unlocked else "Locked - unlock not received"
            )
            line.add_widget(
                label(text, TEAL if defeated and unlocked else GREEN if unlocked else GOLD, 14)
            )
            self.blacklist_rows.add_widget(line)

    def render(self, data):
        data = {**data, "shops": [route_shop(row) for row in data.get("shops", [])]}
        self.locations = {row["location_id"]: row for row in data["shops"]}
        self.location_aliases = shop_location_aliases(data["shops"])
        self.current = data
        self.live = bool(data.get("available"))
        connected = bool(data.get("connected"))
        self.render_blacklist(data)
        if data.get("session_id") != self.hint_session:
            self.hint_session = data.get("session_id")
            self.hint_request_pending = False
            self.hint_waiting_item = None
            self.hint_choice = ""
            self.hint_index = -1
            self.hint_match_signature = None
            self.new_hint.text = ""
            self.hint_filter.text = ""
            self.hint_notice.text = "Hints requested or revealed by anyone in this room."
        self.hint_names = tuple(
            name for name in data.get("hint_items", []) if isinstance(name, str)
        )
        self.update_hint_matches()
        bound = bool(data.get("session_bound"))
        phase = data.get("connection_phase", "")
        busy = self.live and phase in ("connecting", "launching")
        if connected or bound:
            self.server.text = data.get("server") or self.server.text
        elif not self.server.text:
            self.server.text = data.get("server") or (
                self.link_display.server if self.link_display else ""
            )
        self.server.readonly = connected or bound or busy
        self.connect_button.text = (
            "Connected"
            if connected
            else "Connecting..." if busy or self.connection_in_flight else "Connect"
        )
        self.connect_button.disabled = connected or bound or busy or self.connection_in_flight
        self.summary.text = f"Checks {data.get('checks',0)}/{data.get('total_checks') or '—'}   Items received {data.get('received_count',0)}   Cars {sum(c['received'] for c in data['cars'])}/{len(data['cars'])}"
        self.render_cars()
        self.render_hints()
        self.reveal_button.disabled = (
            not connected or not self.selected_part or not self.selected_part.get("item_id")
        )
        if data.get("session_id") != self.text_session:
            self.text_session = data.get("session_id")
            self.text_sequence = 0
            self.text_records = []
            self.log_scroll.data = []
            self.selected_part = None
            self.detail.text = ""
            self.reveal_button.disabled = True
        for record in data.get("text", []):
            if record["id"] > self.text_sequence:
                self.text_sequence = record["id"]
                if is_routine_client_message(record):
                    continue
                color = (
                    "#ff7777"
                    if record.get("level") == "ERROR"
                    else GOLD if record.get("level") == "WARNING" else WHITE
                )
                self.append_log(hint_message(record, self.location_aliases), color)
                self.read_hint_reply(record)
        if connected:
            self.connection_in_flight = False
            self.pending_link = None
            self.credentials_sent = None
            self.set_notice("Connected as " + str(data.get("slot", "")) + ".")
        elif self.live and phase == "error":
            self.connection_in_flight = False
            self.credentials_sent = None
            self.connect_button.disabled = bound
            self.connect_button.text = "Connect"
            self.set_notice(
                data.get("connection_message")
                or "Sign-in failed. Check the server and slot, then retry."
            )
        elif self.live and phase in ("connecting", "launching"):
            self.set_notice(
                data.get("connection_message") or "Signing in. Waiting for server acceptance."
            )
        elif self.live:
            self.set_notice("Disconnected from your Archipelago session.")
        self.forward_pending_link()

    def render_hints(self):
        all_hints = self.current.get("hints", [])
        hints = filter_hints(
            self.hint_filter.text,
            all_hints,
            lambda hint: hint_location(hint, self.locations, self.current.get("slot_id")),
        )
        count = self.current.get("total_checks", 0)
        percent = self.current.get("hint_cost", 0)
        cost = (
            max(1, int(percent * 0.01 * count)) if percent and count else 0 if not percent else "—"
        )
        self.hint_summary.text = f"{len(hints)} of {len(all_hints)} shared hints   |   Points: {self.current.get('hint_points',0)}   |   Hint cost: {cost}"
        signature = json.dumps(
            [hints, self.current.get("slot_id"), self.location_aliases], sort_keys=True
        )
        if signature == self.hint_signature:
            return
        self.hint_signature = signature
        self.hint_rows.clear_widgets()
        for hint in hints:
            row = Surface(
                orientation="horizontal", size_hint_y=None, height=dp(62), padding=(dp(4), 0)
            )
            values = [
                (hint["recipient_name"], 0.18),
                (hint["item_name"], 0.15),
                (hint["finder_name"], 0.20),
                (hint_location(hint, self.locations, self.current.get("slot_id")), 0.16),
                (hint.get("entrance", ""), 0.17),
                ("Found" if hint["found"] else "Not found", 0.14),
            ]
            for text, width in values:
                cell = Label(
                    text=str(text),
                    color=rgba(GREEN if hint["found"] else BLUE),
                    font_size=dp(16),
                    halign="left",
                    valign="middle",
                    size_hint_x=width,
                )
                cell.bind(
                    width=lambda w, v: setattr(w, "text_size", (max(1, v - 6), None)),
                    texture_size=lambda w, v, row=row: setattr(
                        row,
                        "height",
                        max(
                            dp(62),
                            max((c.texture_size[1] for c in row.children), default=0) + dp(12),
                        ),
                    ),
                )
                row.add_widget(cell)
            self.hint_rows.add_widget(row)

    def filter_shared_hints(self):
        self.hints_scroll.scroll_y = 1
        self.render_hints()

    def update_hint_matches(self):
        text = self.new_hint.text.strip()
        if text != self.hint_choice:
            self.hint_choice = ""
        connected = self.live and self.current.get("connected")
        supported = "hint_requests" in self.current.get("capabilities", [])
        self.new_hint.readonly = self.hint_request_pending
        self.hint_button.disabled = (
            not connected
            or not supported
            or self.hint_request_pending
            or text not in self.hint_names
        )
        signature = (text, self.hint_names, self.hint_choice, connected, supported)
        if signature == self.hint_match_signature:
            return
        self.hint_match_signature = signature
        self.hint_matches.clear_widgets()
        self.hint_choices = []
        self.hint_index = -1
        self.hint_matches_scroll.height = 0
        if not text:
            return
        if connected and not supported:
            self.hint_notice.text = "Update NFSMW Setup and nfsmw.apworld to enable hint search."
            return
        if not self.hint_names:
            self.hint_notice.text = "Waiting for item names from the server."
            return
        if text == self.hint_choice:
            return
        matches, total = matching_names(text, self.hint_names)
        self.hint_choices = matches
        self.hint_notice.text = (
            f"Showing {len(matches)} of {total} matches. Keep typing to narrow the list."
            if total > len(matches)
            else (
                f"{total} matching items. Select one, then request its hint."
                if total
                else "No matching items. Try a car name, part, or shorter item name."
            )
        )
        for name in matches:
            item = button(
                name, lambda name=name: self.choose_hint(name), size_hint_y=None, height=dp(40)
            )
            item.background_color = rgba(PANEL)
            item.color = rgba(BLUE)
            item.halign = "left"
            item.padding = (dp(8), 0)
            item.bind(
                width=lambda w, v: setattr(w, "text_size", (max(1, v - dp(24)), None)),
                texture_size=lambda w, v: setattr(w, "height", max(dp(40), v[1] + dp(12))),
            )
            self.hint_matches.add_widget(item)
        self.hint_matches_scroll.height = dp(min(160, 40 * len(matches)))
        self.hint_matches_scroll.scroll_y = 1

    def close_hint_choices(self):
        self.hint_choices = []
        self.hint_index = -1
        self.hint_matches.clear_widgets()
        self.hint_matches_scroll.height = 0

    def move_hint_selection(self, direction):
        if not self.hint_choices:
            return False
        self.hint_index = (
            (0 if direction > 0 else len(self.hint_choices) - 1)
            if self.hint_index < 0
            else (self.hint_index + direction) % len(self.hint_choices)
        )
        for index, item in enumerate(reversed(self.hint_matches.children)):
            item.background_color = rgba(SELECTED if index == self.hint_index else PANEL)
            if index == self.hint_index:
                self.hint_matches_scroll.scroll_to(item, padding=dp(4), animate=False)
        return True

    def choose_hint(self, name):
        self.hint_choice = name
        self.new_hint.text = name
        self.close_hint_choices()
        self.update_hint_matches()
        self.new_hint.focus = True
        self.hint_notice.text = "Selected: " + name

    def read_hint_reply(self, record):
        if not self.hint_waiting_item or record["id"] <= self.hint_request_sequence:
            return
        text = str(record.get("text", ""))
        if text.startswith(
            (
                "You can't afford the hint.",
                "A hint costs ",
                "Nothing found for recognized item",
                "Hint was previously used,",
                "There may be more hintables,",
                "Sorry, ",
            )
        ):
            self.hint_notice.text = text
        elif "[Hint]" in text and normalized(self.hint_waiting_item) in normalized(text):
            self.hint_notice.text = "Hint received: " + self.hint_waiting_item

    def render_cars(self):
        if not hasattr(self, "search"):
            return
        query = self.search.text.strip().casefold()
        rows = [
            r
            for r in self.current["shops"]
            if not query
            or query
            in " ".join(
                str(r.get(k, ""))
                for k in (
                    "car",
                    "category",
                    "tier",
                    "item_name",
                    "recipient_name",
                    "location_name",
                    "store",
                    "store_group",
                    "store_category",
                    "native_menu_name",
                    "display_location_name",
                )
            ).casefold()
        ]
        if query in ("dealership", "performance", "parts"):
            rows = [r for r in rows if r["store"].casefold() == query]
        elif query == "visual":
            rows = [r for r in rows if r["store_group"] == "Visual"]
        active = {r["car"] for r in rows}
        cars = [
            c
            for c in self.current["cars"]
            if c["name"] in active or not query or query in c["name"].casefold()
        ]
        if self.selected_car not in {c["name"] for c in cars}:
            self.selected_car = cars[0]["name"] if cars else ""
            self.category = ""
        signature = json.dumps(
            [
                cars,
                sorted(self.expanded),
                sorted(self.visual_expanded),
                self.selected_car,
                self.category,
            ],
            sort_keys=True,
        )
        if signature != self.car_signature:
            self.car_signature = signature
            self.car_rows.clear_widgets()
            for car in cars:
                name = car["name"]
                expanded = name in self.expanded
                item = button(
                    ("v " if expanded else "> ") + name,
                    lambda name=name: self.select_car(name),
                    size_hint_y=None,
                    height=dp(46),
                )
                item.background_color = rgba(PANEL if name == self.selected_car else BG)
                item.color = rgba(GREEN if car["received"] else DIM)
                item.font_size = dp(15)
                item.text_size = (dp(205), None)
                item.halign = "left"
                self.car_rows.add_widget(item)
                if expanded:
                    car_shops = [r for r in self.current["shops"] if r["car"] == name]
                    categories = list(
                        dict.fromkeys(
                            r["category"]
                            for r in car_shops
                            if r["store_group"] == "Performance" and r["category"]
                        )
                    )
                    for category in ["Dealership", "Visual"] + categories:
                        if category == "Visual":
                            opened = name in self.visual_expanded
                            child = button(
                                "    " + ("v " if opened else "> ") + "Visual",
                                lambda name=name: self.select_visual(name),
                                size_hint_y=None,
                                height=dp(32),
                            )
                            child.background_color = rgba(
                                SELECTED
                                if name == self.selected_car and self.category == "Visual"
                                else BG
                            )
                            child.color = rgba(BLUE)
                            child.halign = "left"
                            child.text_size = (dp(220), None)
                            self.car_rows.add_widget(child)
                            if opened:
                                for visual in visual_categories(car_shops):
                                    selection = "Visual / " + visual
                                    leaf = button(
                                        "        " + visual,
                                        lambda name=name, selection=selection: self.select_category(
                                            name, selection
                                        ),
                                        size_hint_y=None,
                                        height=dp(30),
                                    )
                                    leaf.background_color = rgba(
                                        SELECTED
                                        if name == self.selected_car and self.category == selection
                                        else BG
                                    )
                                    leaf.color = rgba(BLUE)
                                    leaf.halign = "left"
                                    leaf.text_size = (dp(220), None)
                                    self.car_rows.add_widget(leaf)
                            continue
                        child = button(
                            "    " + category,
                            lambda name=name, category=category: self.select_category(
                                name, category
                            ),
                            size_hint_y=None,
                            height=dp(30),
                        )
                        child.background_color = rgba(
                            SELECTED
                            if name == self.selected_car and category == self.category
                            else BG
                        )
                        child.color = rgba(BLUE)
                        child.halign = "left"
                        child.text_size = (dp(235), None)
                        self.car_rows.add_widget(child)

        def selected_category(row):
            if not self.category:
                return True
            if self.category == "Dealership":
                return row["store_group"] == "Dealership"
            if self.category == "Visual":
                return row["store_group"] == "Visual"
            if self.category.startswith("Visual / "):
                return row["store_group"] == "Visual" and row["store_category"] == self.category[9:]
            return row["store_group"] == "Performance" and row["category"] == self.category

        selected = [r for r in rows if r["car"] == self.selected_car and selected_category(r)]
        if self.category == "Visual":
            order = {name: index for index, name in enumerate(visual_categories(selected))}
            selected.sort(
                key=lambda row: (order.get(row["store_category"], len(order)), row["location_id"])
            )
        self.car_heading.text = (self.selected_car or "No matching cars") + (
            (" / " + self.category) if self.category else ""
        )
        signature = json.dumps(selected, sort_keys=True)
        if signature == self.part_signature:
            return
        self.part_signature = signature
        self.part_rows.clear_widgets()
        widths = [110, 180, 300, 160, 100, 130, 160]
        header = Surface(
            color=PANEL, size_hint_y=None, height=dp(46), size_hint_x=None, width=dp(1140)
        )
        for text, width in zip(
            (
                "Store",
                "Part / menu",
                "Reward item",
                "Receiving player",
                "Price",
                "Check status",
                "Item status",
            ),
            widths,
        ):
            header.add_widget(label(text, size=15, size_hint_x=None, width=dp(width)))
        self.part_rows.add_widget(header)
        for row in selected:
            line = Surface(size_hint_y=None, height=dp(52), size_hint_x=None, width=dp(1140))
            part = row["slot_label"]
            state = row.get("status") or (
                "Checked"
                if row["checked"]
                else "Unchecked" if row.get("item_id") else "Waiting for game data"
            )
            values = (
                row["store"],
                part,
                row["item_name"],
                row["recipient_name"] or "—",
                f"${row['price']:,}" if isinstance(row["price"], int) else "—",
                state,
                row.get(
                    "reward_status", "Received" if row.get("reward_received") else "Not received"
                ),
            )
            color = (
                DIM
                if row.get("randomized") is False
                else (
                    GREEN
                    if row.get("reward_received")
                    else (
                        TEAL
                        if row["checked"]
                        else PURPLE if row["hinted"] else GOLD if row["flags"] & 1 else BLUE
                    )
                )
            )
            for text, width in zip(values, widths):
                item = button(
                    str(text),
                    lambda row=row: self.inspect_part(row),
                    size_hint_x=None,
                    width=dp(width),
                )
                item.font_size = dp(16)
                item.background_color = rgba(BG)
                item.color = rgba(color)
                item.text_size = (dp(width - 12), None)
                item.halign = "left"
                item.bind(
                    texture_size=lambda w, v, line=line: setattr(
                        line,
                        "height",
                        max(
                            dp(52),
                            max((c.texture_size[1] for c in line.children), default=0) + dp(14),
                        ),
                    )
                )
                line.add_widget(item)
            self.part_rows.add_widget(line)

    def select_car(self, name):
        self.selected_car = name
        self.category = ""
        if name in self.expanded:
            self.expanded.remove(name)
        else:
            self.expanded.add(name)
        self.reset_parts_view()
        self.render_cars()

    def select_category(self, name, category):
        self.selected_car = name
        self.category = category
        self.reset_parts_view()
        self.render_cars()

    def select_visual(self, name):
        self.selected_car = name
        self.category = "Visual"
        if name in self.visual_expanded:
            self.visual_expanded.remove(name)
        else:
            self.visual_expanded.add(name)
        self.reset_parts_view()
        self.render_cars()

    def reset_parts_view(self):
        self.parts_scroll.scroll_x = 0
        self.parts_scroll.scroll_y = 1
        self.selected_part = None
        self.detail.text = ""
        self.reveal_button.disabled = True

    def filter_cars(self):
        self.category = ""
        self.reset_parts_view()
        self.render_cars()

    def inspect_part(self, row):
        self.selected_part = row
        if row.get("randomized") is False:
            self.detail.text = "Not randomized. This category uses the normal in-game shop."
            self.reveal_button.disabled = True
            return
        self.detail.text = row["item_name"] + (
            (" | " + row["recipient_name"]) if row["recipient_name"] else ""
        )
        self.reveal_button.disabled = not self.current.get("connected") or not row.get("item_id")

    def reveal_selected(self):
        row = self.selected_part
        if row and self.live and self.current.get("connected"):
            self.worker.submit({"action": "reveal", "location": row["location_id"]})

    def append_log(self, text, color=WHITE):
        at_bottom = not self.text_records or self.log_scroll.scroll_y < 0.04
        for line in str(text).splitlines() or [""]:
            self.text_records.append(
                {"text": "[color=" + color.lstrip("#") + "]" + escape_markup(line) + "[/color]"}
            )
        self.text_records = self.text_records[-500:]
        self.refresh_log()
        if at_bottom:
            self._log_follow()
        else:
            self._log_follow.cancel()

    def follow_log(self, _dt=0):
        if self.log_scroll.scroll_y < 0.04:
            self.log_scroll.scroll_y = 0

    def refresh_log(self):
        width = max(dp(32), int(self.log_scroll.width - dp(24)))
        for record in self.text_records:
            if record.get("measured_width") != width:
                measured = CoreMarkupLabel(
                    text=record["text"],
                    font_name=LOG_FONT,
                    font_size=dp(20),
                    line_height=LOG_LINE_HEIGHT,
                    text_size=(max(1, width - dp(4)), None),
                    padding=(dp(2), dp(2)),
                )
                measured.refresh()
                record["size"] = (None, max(dp(30), ceil(measured.texture.height + dp(8))))
                record["measured_width"] = width
        self.log_scroll.data = [
            {"text": record["text"], "size": record["size"]} for record in self.text_records
        ]

    def reflow_log(self, _dt=0):
        at_bottom = self.log_scroll.scroll_y < 0.04
        self.refresh_log()
        if at_bottom:
            self._log_follow()
        else:
            self._log_follow.cancel()

    def set_notice(self, text):
        self.status.text = text
        if self.connection_notice is not None:
            self.connection_notice.text = text

    def send(self):
        text = self.command.text.strip()
        if not text:
            return
        self.command.text = ""
        self.select_tab("Archipelago")
        if text.casefold() == "/help" and not self.current.get("connected"):
            self.append_log(
                "/help\n    Show client commands.\n/received\n    List received items.\n/missing [text]\n    List missing checks.\n/items\n    List item names.\n/locations\n    List location names.\n/item_groups [key]\n    List item groups.\n/location_groups [key]\n    List location groups.\n!hint <item>\n    Request a server hint while connected."
            )
            return
        self.send_command(text)

    def send_command(self, text):
        if not self.live or not self.current.get("connected"):
            self.set_notice(
                "Disconnected from your Archipelago session."
                if self.live
                else "Connection client is not running."
            )
            return
        self.worker.submit({"action": "command", "text": text})

    def request_hint(self):
        text = self.new_hint.text.strip()
        if not text or self.hint_request_pending:
            return
        if not self.live or not self.current.get("connected"):
            self.hint_notice.text = (
                "Disconnected from your Archipelago session."
                if self.live
                else "Connection client is not running."
            )
            return
        if "hint_requests" not in self.current.get("capabilities", []):
            self.hint_notice.text = "Update NFSMW Setup and nfsmw.apworld to enable hint search."
            return
        if self.hint_choices and (self.hint_index >= 0 or text not in self.hint_names):
            self.choose_hint(self.hint_choices[max(0, self.hint_index)])
            return
        if text not in self.hint_names:
            self.hint_notice.text = "Choose an item from the matches below."
            return
        if not self.worker.submit({"action": "hint_request", "item": text}):
            self.hint_notice.text = "Too many requests are pending. Try again in a moment."
            return
        self.hint_request_pending = True
        self.hint_waiting_item = text
        self.hint_request_sequence = self.text_sequence
        self.close_hint_choices()
        self.update_hint_matches()
        self.hint_notice.text = "Requesting: " + text

    def connect_clicked(self):
        if self.current.get("connected") or self.current.get("session_bound"):
            self.set_notice("The current game session is already selected.")
            return
        if self.connection_in_flight:
            return
        try:
            link = from_fields(self.server.text)
        except ValueError as exc:
            self.set_notice(str(exc))
            self.server.focus = True
            return
        self.server.text = link.server
        explicit = bool(link.slot)
        if self.pending_link and self.pending_link.server == link.server:
            link = self.pending_link
            explicit = bool(link.slot)
        elif self.link_display and self.link_display.server == link.server:
            link = ConnectionLink(link.server, self.link_display.slot)
        if explicit and self.current.get("connection_phase") != "error":
            self.begin_connection(link)
        else:
            self.open_connection_dialog(link)

    def open_connection_dialog(self, link):
        if self.connection_dialog is not None:
            return
        body = Surface(orientation="vertical", spacing=dp(8), padding=dp(10))
        self.connection_fields = {}
        for key, caption, value in (
            ("server", "Server:", link.server),
            ("slot", "Player / slot:", link.slot),
            ("password", "Password (optional):", link.password),
        ):
            row = Surface(size_hint_y=None, height=dp(38), spacing=dp(8))
            row.add_widget(label(caption, size=15, size_hint_x=None, width=dp(155)))
            field = Entry(text=value, password=key == "password")
            row.add_widget(field)
            body.add_widget(row)
            self.connection_fields[key] = field
            field.bind(on_text_validate=lambda *_: self.submit_connection_dialog())
        fields = self.connection_fields
        fields["server"].focus_next = fields["slot"]
        fields["slot"].focus_previous = fields["server"]
        fields["slot"].focus_next = fields["password"]
        fields["password"].focus_previous = fields["slot"]
        self.connection_notice = label(
            "Enter the exact player/slot name from the room page.",
            WHITE,
            15,
            size_hint_y=None,
            height=dp(76),
        )
        body.add_widget(self.connection_notice)
        buttons = Surface(size_hint_y=None, height=dp(36), spacing=dp(12))
        buttons.add_widget(button("Cancel", self.cancel_connection_dialog))
        buttons.add_widget(button("Connect", self.submit_connection_dialog))
        body.add_widget(buttons)
        popup = Popup(
            title="Connect to Archipelago",
            content=body,
            size_hint=(0.9, None),
            height=dp(340),
            auto_dismiss=False,
            background="",
            background_color=rgba(PANEL),
            separator_color=rgba(BLUE),
        )
        self.connection_dialog = popup
        popup.bind(on_dismiss=self.close_connection_dialog)
        popup.open()
        Clock.schedule_once(lambda *_: setattr(fields["slot"], "focus", True), 0.1)

    def cancel_connection_dialog(self):
        self.pending_link = None
        self.link_attempted = None
        if self.connection_dialog:
            self.connection_dialog.dismiss()

    def close_connection_dialog(self, *_):
        if "password" in self.connection_fields:
            self.connection_fields["password"].text = ""
        self.connection_fields = {}
        self.connection_dialog = None
        self.connection_notice = None

    def submit_connection_dialog(self):
        try:
            link = from_fields(
                *(self.connection_fields[k].text for k in ("server", "slot", "password"))
            )
            if not link.slot:
                raise ValueError("Enter the exact player/slot name from the room page.")
        except ValueError as exc:
            self.set_notice(str(exc))
            return
        self.server.text = link.server
        self.begin_connection(link)

    def begin_connection(self, link):
        if self.current.get("connected") or self.current.get("session_bound"):
            self.set_notice("The current game session stays connected.")
            return False
        if not self.live:
            self.set_notice("Connection client is not running.")
            return False
        if "website_links" not in self.current.get("capabilities", []):
            self.set_notice("Update the game-folder connection client to version 1.0.1.")
            return False
        if not self.current.get("form_open"):
            self.set_notice("The client is still starting. Try again in a moment.")
            return False
        if self.connection_in_flight:
            return False
        if not self.worker.submit({"action": "connection_link", "connection": link.payload()}):
            self.set_notice("Too many requests are pending. Try again in a moment.")
            return False
        self.connection_in_flight = True
        self.credentials_sent = ConnectionLink(link.server, link.slot)
        self.link_display = ConnectionLink(link.server, link.slot)
        self.link_attempted = self.current.get("session_id")
        self.connect_button.text = "Connecting..."
        self.connect_button.disabled = True
        self.set_notice(
            "Signing in as "
            + (link.slot or "the selected slot")
            + ". Waiting for server acceptance."
        )
        return True

    def forward_pending_link(self):
        if self.pending_link is None:
            return
        if self.current.get("connected") or self.current.get("session_bound"):
            self.pending_link = None
            self.set_notice("The existing game connection stays active.")
            return
        if not self.live:
            self.set_notice("Connection client is not running.")
            return
        if self.connection_dialog is not None or self.connection_in_flight:
            return
        session = self.current.get("session_id")
        if self.current.get("form_open") and session != self.link_attempted:
            if self.pending_link.slot:
                self.begin_connection(self.pending_link)
            else:
                self.open_connection_dialog(self.pending_link)

    def poll(self, _dt=0):
        if self.closed:
            return False
        try:
            while True:
                kind, value = self.worker.results.get_nowait()
                if kind == "snapshot":
                    self.render(value)
                elif kind == "offline":
                    self.live = False
                    self.current.update(
                        available=False, connected=False, form_open=False, session_bound=False
                    )
                    self.reveal_button.disabled = True
                    self.connection_in_flight = False
                    self.credentials_sent = None
                    self.hint_request_pending = False
                    self.hint_waiting_item = None
                    self.update_hint_matches()
                    self.hint_notice.text = "Connection client is not running."
                    self.server.readonly = False
                    self.connect_button.disabled = False
                    self.connect_button.text = "Connect"
                    if self.pending_link:
                        self.forward_pending_link()
                    else:
                        self.set_notice("Connection client is not running.")
                elif kind == "action":
                    if value.get("operation") == "hint_request":
                        if not self.hint_request_pending:
                            continue
                        self.hint_request_pending = False
                        if value.get("ok"):
                            self.hint_choice = ""
                            self.new_hint.text = ""
                            self.hint_notice.text = value.get(
                                "message", "Hint requested. Waiting for a reply."
                            )
                        else:
                            self.hint_waiting_item = None
                            self.hint_notice.text = value.get(
                                "error", "Could not request the hint. Try again."
                            )
                        self.update_hint_matches()
                    elif value.get("operation") == "connection_link":
                        self.pending_link = None
                        if value.get("ok"):
                            self.connection_in_flight = False
                            if self.connection_dialog:
                                self.connection_dialog.dismiss()
                            self.set_notice(
                                "Sign-in sent. Waiting for the server."
                                if value.get("started")
                                else value.get(
                                    "message", "Enter your slot in the connection screen."
                                )
                            )
                        else:
                            self.connection_in_flight = False
                            self.credentials_sent = None
                            self.link_attempted = None
                            self.connect_button.disabled = False
                            self.connect_button.text = "Connect"
                            self.set_notice(
                                value.get("error", "Could not send the connection request.")
                            )
                    elif value.get("operation") == "reveal" and value.get("ok"):
                        self.set_notice(value.get("message", "Hint reveal requested."))
                    elif not value.get("ok"):
                        message = value.get("error", "The connection client is not available.")
                        self.set_notice(message)
                        self.append_log(message, GOLD)
        except queue.Empty:
            pass

    def on_stop(self):
        self.closed = True
        self.pending_link = None
        self.credentials_sent = None
        self._log_reflow.cancel()
        self._log_follow.cancel()
        if self.connection_dialog:
            self.connection_dialog.dismiss()
        self.worker.close()
        self.resource_stack.close()
