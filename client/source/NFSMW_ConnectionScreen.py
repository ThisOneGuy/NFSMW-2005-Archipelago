from __future__ import annotations

import asyncio
import textwrap
import NFSMW_PoliceBadge as police_badge

INK = "#abe13b"
DIM = "#71932a"
FOCUS = "#1c2708"
FIELDS = ("server", "slot", "password", "seed")
LABELS = ("SERVER:", "SLOT NAME:", "PASSWORD:", "SEED (OPTIONAL):")


def terminal_layout(width, height):
    scale = min(width / 960, height / 540)
    return scale, (width - 960 * scale) / 2, (height - 540 * scale) / 2


class ConnectionScreen:
    def __init__(self, ctx):
        import tkinter as tk
        from tkinter import font as tkfont

        self.tk = tk
        self.ctx = ctx
        self.closed = False
        self.hidden_for_game = False
        self.phase = "input"
        self.connect_task = None
        self.signature = None
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            raise RuntimeError(
                "Could not open the fullscreen connection screen: " + str(exc)
            ) from exc
        self.root.title("NFSMW Archipelago — Multiworld Access")
        self.root.configure(background="black")
        self.root.attributes("-fullscreen", True)
        self.root.protocol("WM_DELETE_WINDOW", self.cancel)
        self.canvas = tk.Canvas(self.root, background="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.values = {name: tk.StringVar(master=self.root, value="") for name in FIELDS}
        self.field_font = tkfont.Font(root=self.root, family="Consolas", size=-15)
        self.labels = []
        self.entries = []
        for name, caption in zip(FIELDS, LABELS):
            label = tk.Label(
                self.canvas,
                text=caption,
                font=self.field_font,
                background="black",
                foreground=DIM,
                anchor="w",
                padx=0,
                pady=0,
                borderwidth=0,
                highlightthickness=0,
            )
            self.labels.append(label)
            entry = tk.Entry(
                self.canvas,
                textvariable=self.values[name],
                font=self.field_font,
                justify="left",
                background="black",
                foreground=INK,
                disabledbackground="black",
                disabledforeground=DIM,
                insertbackground=INK,
                selectbackground=INK,
                selectforeground="black",
                relief="flat",
                borderwidth=0,
                highlightthickness=0,
                show="X" if name == "password" else "",
            )
            entry.bind("<FocusIn>", lambda event: self.draw())

            entry.bind("<Control-a>", self.select_all)
            self.entries.append(entry)
        self.button = tk.Button(
            self.canvas,
            text="[ ENTER ]  SIGN IN",
            command=self.submit,
            foreground=INK,
            background=FOCUS,
            activeforeground="black",
            activebackground=INK,
            relief="flat",
            borderwidth=0,
            highlightbackground=INK,
            highlightthickness=1,
            takefocus=False,
        )
        self.root.bind("<Return>", lambda event: self.submit())
        self.root.bind("<Escape>", lambda event: self.cancel())
        self.canvas.bind("<Configure>", lambda event: self.draw())
        self.root.after_idle(self.entries[0].focus_force)

    @staticmethod
    def select_all(event):
        event.widget.selection_range(0, "end")
        event.widget.icursor("end")
        return "break"

    def submit(self):
        if self.closed or self.phase not in ("input", "error"):
            return
        if self.connect_task is not None and not self.connect_task.done():
            return

        self.phase = "connecting"
        self.ctx.connection_message = {
            "phase": "connecting",
            "message": "Connecting to Archipelago...",
        }
        payload = {name: value.get() for name, value in self.values.items()}
        self.connect_task = asyncio.create_task(self._connect(payload))
        self.draw()

    def accept_connection_link(self, payload):
        from NFSMW_ConnectionLink import validate_payload

        payload = validate_payload(payload)
        if (
            self.ctx.ap_connected()
            or getattr(self.ctx, "session_key", "")
            or getattr(self.ctx, "game_ready_pids", set())
        ):
            return {
                "ok": False,
                "error": "The current game session stays connected. Close the game before changing rooms.",
            }
        if self.closed or self.hidden_for_game or self.phase not in ("input", "error"):
            return {
                "ok": False,
                "error": "The connection screen is already signing in or starting the game.",
            }
        if self.connect_task is not None and not self.connect_task.done():
            return {"ok": False, "error": "A connection attempt is already running."}
        for key, value in payload.items():
            self.values[key].set(value)
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        if payload["slot"]:
            self.submit()
            return {"ok": True, "started": True}
        self.draw()
        return {
            "ok": True,
            "started": False,
            "message": "Enter your slot name in the separate connection screen.",
        }

    async def _connect(self, payload):
        try:
            await self.ctx.connect_from_game(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.ctx.connection_notice("error", "Connection failed: " + str(exc))

    def cancel(self):

        self.ctx.exit_event.set()
        self.close()

    def hide_during_game_launch(self):

        if not self.closed and not self.hidden_for_game:
            self.root.withdraw()
            self.hidden_for_game = True

    def show_after_game_launch_failure(self):

        if not self.closed and self.hidden_for_game:
            self.root.deiconify()
            self.root.attributes("-fullscreen", True)
            self.hidden_for_game = False
            self.draw()

    def close(self):
        if self.closed:
            return
        self.closed = True
        if (
            self.connect_task is not None
            and not self.connect_task.done()
            and self.connect_task is not asyncio.current_task()
        ):
            self.connect_task.cancel()
        self.root.destroy()

    async def run(self):
        try:
            while not self.closed and not self.ctx.exit_event.is_set():
                notice = self.ctx.connection_message
                signature = (notice.get("phase"), notice.get("message"))
                if signature != self.signature:
                    self.signature = signature
                    self.phase = notice.get("phase", "input")
                    self.draw()
                self.root.update()
                await asyncio.sleep(0.025)
        except self.tk.TclError:
            self.ctx.exit_event.set()
        finally:
            if not self.closed:
                self.close()
            if self.connect_task is not None:
                await asyncio.gather(self.connect_task, return_exceptions=True)

    def draw(self):
        if self.closed:
            return
        canvas = self.canvas
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 10 or height < 10:
            return
        unit, ox, oy = terminal_layout(width, height)
        canvas.delete("terminal")

        def rect(x, y, w, h, color=INK, outline="", line=1):
            canvas.create_rectangle(
                ox + x * unit,
                oy + y * unit,
                ox + (x + w) * unit,
                oy + (y + h) * unit,
                fill=color,
                outline=outline,
                width=max(1, line * unit),
                tags="terminal",
            )

        def text(value, x, y, size=15, color=INK, anchor="nw", **kwargs):
            canvas.create_text(
                ox + x * unit,
                oy + y * unit,
                text=value,
                fill=color,
                anchor=anchor,
                font=("Consolas", -max(9, round(size * unit))),
                tags="terminal",
                **kwargs,
            )

        def place(widget, x, y, w, h):
            left, top = round(ox + x * unit), round(oy + y * unit)
            right, bottom = round(ox + (x + w) * unit), round(oy + (y + h) * unit)
            widget.place(x=left, y=top, width=right - left, height=bottom - top)

        def button_place(widget, x, y, w, h):
            place(widget, x, y, w, h)
            widget.configure(font=("Consolas", -max(9, round(15 * unit))))

        badge_x, badge_y = police_badge.ORIGIN
        for polygon in police_badge.POLYGONS:
            coordinates = [
                value
                for x, y in polygon
                for value in (ox + (badge_x + x) * unit, oy + (badge_y + y) * unit)
            ]
            canvas.create_polygon(*coordinates, fill=INK, outline="", width=0, tags="terminal")
        text("R O C K P O R T   P O L I C E   D E P A R T M E N T", 480, 176, 18, anchor="n")
        text("ARCHIPELAGO  /  MULTIWORLD ACCESS", 480, 204, 13, DIM, "n")
        rect(205, 228, 550, 136, "", INK, 3)
        editable = self.phase in ("input", "error")
        active = self.root.focus_get()
        self.field_font.configure(size=-max(9, round(15 * unit)))
        for row, (label, entry) in enumerate(zip(self.labels, self.entries)):
            y = 240 + row * 29
            selected = editable and active is entry
            if selected:
                rect(214, y - 5, 532, 25, FOCUS)
                rect(214, y - 5, 3, 25)
            label.configure(
                foreground=INK if selected else DIM, background=FOCUS if selected else "black"
            )
            entry.configure(
                state="normal" if editable else "disabled",
                background=FOCUS if selected else "black",
            )

            place(label, 227, y - 5, 178, 25)
            place(entry, 409, y - 5, 329, 25)
        launch_failed = self.phase == "error" and getattr(self.ctx, "game_launch_failed", False)
        heading = (
            "GAME LAUNCH FAILED"
            if launch_failed
            else (
                "CONNECTION FAILED"
                if self.phase == "error"
                else (
                    "SIGN IN TO MULTIWORLD"
                    if editable
                    else "OPENING YOUR CAREER" if self.phase == "relaunch" else "SIGNING IN --/"
                )
            )
        )
        text(heading, 480, 387, 19, anchor="n")
        message = self.ctx.connection_message.get(
            "message", "Enter your server address and exact slot name."
        )
        lines = textwrap.wrap(message, width=88)
        if len(lines) > 3:
            lines = lines[:3]
            lines[-1] = lines[-1][:84] + "..."
        text("\n".join(lines), 480, 417, 11, DIM, "n", width=660 * unit, justify="center")
        for x in range(171, 789, 10):
            rect(x, 458, 5, 5)
        button_place(self.button, 205, 486, 191, 27)
        self.button.configure(
            state="normal" if editable else "disabled",
            text="[ ENTER ] RETRY GAME" if launch_failed else "[ ENTER ]  SIGN IN",
        )
        text("[ TAB ] NEXT FIELD", 420, 491, 14)
        text("[ ESC ] EXIT", 638, 491, 14)
        text(
            "SERVER: host:port    PASSWORD / SEED: optional; seed is read from the server",
            480,
            522,
            11,
            DIM,
            "n",
        )
