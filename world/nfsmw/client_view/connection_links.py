from __future__ import annotations
from dataclasses import dataclass, field
import re
from urllib.parse import urlsplit, urlunsplit, unquote, parse_qsl, urlencode

GAME = "Need for Speed: Most Wanted"


@dataclass(frozen=True)
class ConnectionLink:
    server: str
    slot: str = ""
    password: str = field(default="", repr=False)

    def payload(self):
        return {"server": self.server, "slot": self.slot, "password": self.password, "seed": ""}


def validate_payload(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid connection link.")
    server, slot, password = (value.get(k, "") for k in ("server", "slot", "password"))
    if not all(isinstance(v, str) for v in (server, slot, password)):
        raise ValueError("Invalid connection fields.")
    if not server or len(server) > 240 or len(slot) > 31 or len(password) > 1024:
        raise ValueError("The connection link contains invalid field lengths.")
    if any(ord(c) < 32 for c in server + slot + password):
        raise ValueError("Control characters are not allowed in connection fields.")
    if slot and (
        not slot.isascii()
        or slot in (".", "..")
        or slot[-1] in ". "
        or any(c in '<>:"/\\|?*' for c in slot)
        or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", slot)
    ):
        raise ValueError("The slot name must be a valid NFSMW profile name.")
    try:
        parsed = urlsplit(server if "://" in server else "ws://" + server)
        if (
            parsed.scheme not in ("ws", "wss")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
    except ValueError:
        raise ValueError("The connection link has an invalid server address.") from None
    return {"server": server, "slot": slot, "password": password, "seed": ""}


def parse_link(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("Invalid Archipelago connection link.")
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "archipelago" or not parsed.hostname or parsed.fragment:
            raise ValueError
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise ValueError("Invalid Archipelago connection link.") from None
    query = parse_qsl(parsed.query, keep_blank_values=True)
    games = [v for k, v in query if k == "game"]
    if games and any(v != GAME for v in games):
        raise ValueError("This connection link belongs to another game.")
    host = parsed.hostname
    if ":" in host:
        host = "[" + host + "]"
    authority = host + (":" + str(port) if port is not None else "")
    path = "" if parsed.path in ("", "/") else parsed.path
    transport_query = urlencode([(k, v) for k, v in query if k != "game"])
    server = (
        urlunsplit(("ws", authority, path, transport_query, ""))
        if path or transport_query
        else authority
    )
    slot = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    payload = validate_payload({"server": server, "slot": slot, "password": password})
    return ConnectionLink(payload["server"], payload["slot"], payload["password"])


def from_fields(server, slot="", password=""):
    if not all(isinstance(v, str) for v in (server, slot, password)):
        raise ValueError("Enter a server address and player/slot name.")
    server = server.strip()
    slot = slot.strip()
    if server.startswith("archipelago://"):
        link = parse_link(server)
        server = link.server
        slot = slot or link.slot
        password = password or link.password
    payload = validate_payload({"server": server, "slot": slot, "password": password})
    parsed = urlsplit(server if "://" in server else "ws://" + server)
    if parsed.fragment:
        raise ValueError("Enter a server address without a fragment.")
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if any(k == "game" and v != GAME for k, v in query):
        raise ValueError("This connection link belongs to another game.")
    authority = parsed.hostname
    if ":" in authority:
        authority = "[" + authority + "]"
    if parsed.port is not None:
        authority += ":" + str(parsed.port)
    path = "" if parsed.path in ("", "/") else parsed.path
    query = urlencode([(k, v) for k, v in query if k != "game"])
    normalized = urlunsplit((parsed.scheme, authority, path, query, ""))
    if parsed.scheme == "ws" and not path and not query:
        normalized = authority
    return ConnectionLink(normalized, payload["slot"], payload["password"])
