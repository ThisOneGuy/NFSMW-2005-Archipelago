from __future__ import annotations

import asyncio
import concurrent.futures
import json
import shlex
import typing
import builtins
import os
import itertools
import subprocess
import sys
import pickle
import functools
import io
import collections
import importlib
import logging
import warnings
import pathlib

from argparse import Namespace
from collections.abc import Collection, Iterable, Sequence
from datetime import datetime, timezone
from shutil import which

from settings import Settings, get_settings
from time import sleep
from typing import BinaryIO, Coroutine, Generic, Mapping, Optional, Set, Dict, Any, TypeVar, Union, TypeGuard
from yaml import load, load_all, dump
from pathspec import PathSpec, GitIgnoreSpec
from typing_extensions import deprecated

try:
    from yaml import CLoader as UnsafeLoader, CSafeLoader as SafeLoader, CDumper as Dumper
except ImportError:
    from yaml import Loader as UnsafeLoader, SafeLoader, Dumper

if typing.TYPE_CHECKING:
    import tkinter
    from BaseClasses import Region
    import multiprocessing


def tuplize_version(version: str) -> Version:
    return Version(*(int(piece) for piece in version.split(".")))


class Version(typing.NamedTuple):
    major: int
    minor: int
    build: int

    def as_simple_string(self) -> str:
        return ".".join(str(item) for item in self)


__version__ = "0.6.8"
version_tuple = tuplize_version(__version__)

is_linux = sys.platform.startswith("linux")
is_macos = sys.platform == "darwin"
is_windows = sys.platform in ("win32", "cygwin", "msys")


def int16_as_bytes(value: int) -> typing.List[int]:
    value = value & 0xFFFF
    return [value & 0xFF, (value >> 8) & 0xFF]


def int32_as_bytes(value: int) -> typing.List[int]:
    value = value & 0xFFFFFFFF
    return [value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF, (value >> 24) & 0xFF]


def pc_to_snes(value: int) -> int:
    return ((value << 1) & 0x7F0000) | (value & 0x7FFF) | 0x8000


def snes_to_pc(value: int) -> int:
    return ((value & 0x7F0000) >> 1) | (value & 0x7FFF)


RetType = typing.TypeVar("RetType")
S = typing.TypeVar("S")
T = typing.TypeVar("T")


def cache_argsless(function: typing.Callable[[], RetType]) -> typing.Callable[[], RetType]:
    assert not function.__code__.co_argcount, "Can only cache 0 argument functions with this cache."

    sentinel = object()
    result: typing.Union[object, RetType] = sentinel

    def _wrap() -> RetType:
        nonlocal result
        if result is sentinel:
            result = function()
        return typing.cast(RetType, result)

    return _wrap


def cache_self1(function: typing.Callable[[S, T], RetType]) -> typing.Callable[[S, T], RetType]:


    assert function.__code__.co_argcount == 2, "Can only cache 2 argument functions with this cache."

    cache_name = f"__cache_{function.__name__}__"

    @functools.wraps(function)
    def wrap(self: S, arg: T) -> RetType:
        cache: Optional[Dict[T, RetType]] = getattr(self, cache_name, None)
        if cache is None:
            res = function(self, arg)
            setattr(self, cache_name, {arg: res})
            return res
        try:
            return cache[arg]
        except KeyError:
            res = function(self, arg)
            cache[arg] = res
            return res

    wrap.__defaults__ = function.__defaults__

    return wrap


def is_frozen() -> bool:
    return typing.cast(bool, getattr(sys, 'frozen', False))


def local_path(*path: str) -> str:

    if hasattr(local_path, 'cached_path'):
        pass
    elif is_frozen():
        if hasattr(sys, "_MEIPASS"):

            local_path.cached_path = sys._MEIPASS
        else:

            local_path.cached_path = os.path.dirname(os.path.abspath(sys.argv[0]))
    else:
        import __main__
        if globals().get("__file__") and os.path.isfile(__file__):

            local_path.cached_path = os.path.dirname(os.path.abspath(__file__))
        elif hasattr(__main__, "__file__") and os.path.isfile(__main__.__file__):

            local_path.cached_path = os.path.dirname(os.path.abspath(__main__.__file__))
        else:

            local_path.cached_path = os.path.abspath(".")

    return os.path.join(local_path.cached_path, *path)


def home_path(*path: str) -> str:

    if hasattr(home_path, 'cached_path'):
        pass
    elif sys.platform.startswith('linux'):
        xdg_data_home = os.getenv('XDG_DATA_HOME', os.path.expanduser('~/.local/share'))
        home_path.cached_path = xdg_data_home + '/Archipelago'
        if not os.path.isdir(home_path.cached_path):
            legacy_home_path = os.path.expanduser('~/Archipelago')
            if os.path.isdir(legacy_home_path):
                os.renames(legacy_home_path, home_path.cached_path)
                os.symlink(home_path.cached_path, legacy_home_path)
            else:
                os.makedirs(home_path.cached_path, 0o700, exist_ok=True)
    elif sys.platform == 'darwin':
        import platformdirs
        home_path.cached_path = platformdirs.user_data_dir("Archipelago", False)
        os.makedirs(home_path.cached_path, 0o700, exist_ok=True)
    else:

        home_path.cached_path = local_path()

    return os.path.join(home_path.cached_path, *path)


def user_path(*path: str) -> str:

    if hasattr(user_path, "cached_path"):
        pass
    elif os.access(local_path(), os.W_OK) and not (is_macos and is_frozen()):
        user_path.cached_path = local_path()
    else:
        user_path.cached_path = home_path()

        if user_path.cached_path != local_path():
            import filecmp
            if not os.path.exists(user_path("manifest.json")) or \
                    not os.path.exists(local_path("manifest.json")) or \
                    not filecmp.cmp(local_path("manifest.json"), user_path("manifest.json"), shallow=True):
                import shutil
                for dn in ("Players", "data/sprites", "data/lua"):
                    shutil.copytree(local_path(dn), user_path(dn), dirs_exist_ok=True)
                if not os.path.exists(local_path("manifest.json")):
                    warnings.warn(f"Upgrading {user_path()} from something that is not a proper install")
                else:
                    shutil.copy2(local_path("manifest.json"), user_path("manifest.json"))
            os.makedirs(user_path("worlds"), exist_ok=True)

    return os.path.join(user_path.cached_path, *path)


def cache_path(*path: str) -> str:

    if hasattr(cache_path, "cached_path"):
        pass
    else:
        import platformdirs
        cache_path.cached_path = platformdirs.user_cache_dir("Archipelago", False)

    return os.path.join(cache_path.cached_path, *path)


def output_path(*path: str) -> str:
    if hasattr(output_path, 'cached_path'):
        return os.path.join(output_path.cached_path, *path)
    output_path.cached_path = user_path(get_settings()["general_options"]["output_path"])
    path = os.path.join(output_path.cached_path, *path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def open_file(filename: typing.Union[str, "pathlib.Path"]) -> None:
    if is_windows:
        os.startfile(filename)
    else:
        from shutil import which
        open_command = which("open") if is_macos else (which("xdg-open") or which("gnome-open") or which("kde-open"))
        assert open_command, "Didn't find program for open_file! Please report this together with system details."

        env = env_cleared_lib_path()
        subprocess.call([open_command, filename], env=env)


class UniqueKeyLoader(SafeLoader):
    def construct_mapping(self, node, deep=False):
        mapping = set()
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                logging.error(f"YAML duplicates sanity check failed{key_node.start_mark}")
                raise KeyError(f"Duplicate key {key} found in YAML. Already found keys: {mapping}.")
            if (str(key).startswith("+") and (str(key)[1:] in mapping)) or (f"+{key}" in mapping):
                logging.error(f"YAML merge duplicates sanity check failed{key_node.start_mark}")
                raise KeyError(f"Equivalent key {key} found in YAML. Already found keys: {mapping}.")
            mapping.add(key)
        return super().construct_mapping(node, deep)


parse_yaml = functools.partial(load, Loader=UniqueKeyLoader)
parse_yamls = functools.partial(load_all, Loader=UniqueKeyLoader)
unsafe_parse_yaml = functools.partial(load, Loader=UnsafeLoader)

del load, load_all


def get_cert_none_ssl_context():
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


@cache_argsless
def get_public_ipv4() -> str:
    import socket
    import urllib.request
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except socket.gaierror:

        warnings.warn("Could not resolve own hostname, falling back to 127.0.0.1")
        ip = "127.0.0.1"

    ctx = get_cert_none_ssl_context()
    try:
        ip = urllib.request.urlopen("https://checkip.amazonaws.com/", context=ctx, timeout=10).read().decode("utf8").strip()
    except Exception as e:

        try:
            ip = urllib.request.urlopen("https://v4.ident.me", context=ctx, timeout=10).read().decode("utf8").strip()
        except Exception:
            logging.exception(e)
            pass
    return ip


@cache_argsless
def get_public_ipv6() -> str:
    import socket
    import urllib.request
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except socket.gaierror:

        warnings.warn("Could not resolve own hostname, falling back to ::1")
        ip = "::1"

    ctx = get_cert_none_ssl_context()
    try:
        ip = urllib.request.urlopen("https://v6.ident.me", context=ctx, timeout=10).read().decode("utf8").strip()
    except Exception as e:
        logging.exception(e)
        pass
    return ip


@deprecated("Utils.get_options() is deprecated. Use the settings API instead.")
def get_options() -> Settings:
    deprecate("Utils.get_options() is deprecated. Use the settings API instead.")
    return get_settings()


def persistent_store(category: str, key: str, value: typing.Any, force_store: bool = False):
    storage = persistent_load()
    if not force_store and category in storage and key in storage[category] and storage[category][key] == value:
        return
    category_dict = storage.setdefault(category, {})
    category_dict[key] = value
    path = user_path("_persistent_storage.yaml")
    with open(path, "wt") as f:
        f.write(dump(storage, Dumper=Dumper))


def persistent_load() -> Dict[str, Dict[str, Any]]:
    storage: Union[Dict[str, Dict[str, Any]], None] = getattr(persistent_load, "storage", None)
    if storage:
        return storage
    path = user_path("_persistent_storage.yaml")
    storage = {}
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                storage = unsafe_parse_yaml(f.read())
            if "datapackage" in storage:
                del storage["datapackage"]
                logging.debug("Removed old datapackage from persistent storage")
        except Exception as e:
            logging.debug(f"Could not read store: {e}")
    if storage is None:
        storage = {}
    setattr(persistent_load, "storage", storage)
    return storage


def get_file_safe_name(name: str) -> str:
    return "".join(c for c in name if c not in '<>:"/\\|?*')


def load_data_package_for_checksum(game: str, checksum: typing.Optional[str]) -> Dict[str, Any]:
    if checksum and game:
        if checksum != get_file_safe_name(checksum):
            raise ValueError(f"Bad symbols in checksum: {checksum}")
        path = cache_path("datapackage", get_file_safe_name(game), f"{checksum}.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            except Exception as e:
                logging.debug(f"Could not load data package: {e}")


    return {}


def store_data_package_for_checksum(game: str, data: typing.Dict[str, Any]) -> None:
    checksum = data.get("checksum")
    if checksum and game:
        if checksum != get_file_safe_name(checksum):
            raise ValueError(f"Bad symbols in checksum: {checksum}")
        game_folder = cache_path("datapackage", get_file_safe_name(game))
        os.makedirs(game_folder, exist_ok=True)
        try:
            with open(os.path.join(game_folder, f"{checksum}.json"), "w", encoding="utf-8-sig") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        except Exception as e:
            logging.debug(f"Could not store data package: {e}")


def read_apignore(filename: str | pathlib.Path) -> PathSpec | None:
    try:
        with open(filename) as ignore_file:
            return GitIgnoreSpec.from_lines(ignore_file)
    except FileNotFoundError:
        return None


def get_default_adjuster_settings(game_name: str) -> Namespace:
    import LttPAdjuster
    adjuster_settings = Namespace()
    if game_name == LttPAdjuster.GAME_ALTTP:
        return LttPAdjuster.get_argparser().parse_known_args(args=[])[0]

    return adjuster_settings


def get_adjuster_settings_no_defaults(game_name: str) -> Namespace:
    return persistent_load().get("adjuster", {}).get(game_name, Namespace())


def get_adjuster_settings(game_name: str) -> Namespace:
    adjuster_settings = get_adjuster_settings_no_defaults(game_name)
    default_settings = get_default_adjuster_settings(game_name)


    return Namespace(**vars(adjuster_settings), **{
        k: v for k, v in vars(default_settings).items() if k not in vars(adjuster_settings)
    })


@cache_argsless
def get_unique_identifier():
    common_path = cache_path("common.json")
    try:
        with open(common_path) as f:
            common_file = json.load(f)
            uuid = common_file.get("uuid", None)
    except FileNotFoundError:
        common_file = {}
        uuid = None

    if uuid:
        return uuid

    from uuid import uuid4
    uuid = str(uuid4())
    common_file["uuid"] = uuid

    cache_folder = os.path.dirname(common_path)
    os.makedirs(cache_folder, exist_ok=True)
    with open(common_path, "w") as f:
        json.dump(common_file, f, separators=(",", ":"))
    return uuid


safe_builtins = frozenset((
    'set',
    'frozenset',
))


class RestrictedUnpickler(pickle.Unpickler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(RestrictedUnpickler, self).__init__(*args, **kwargs)
        self.options_module = importlib.import_module("Options")
        self.net_utils_module = importlib.import_module("NetUtils")

    def find_class(self, module: str, name: str) -> type:
        if module == "builtins" and name in safe_builtins:
            return getattr(builtins, name)


        if module == "collections" and name == "Counter":
            return collections.Counter

        if module == "NetUtils" and name in {"NetworkItem", "ClientStatus", "Hint",
                                             "SlotType", "NetworkSlot", "HintStatus"}:
            return getattr(self.net_utils_module, name)


        if module.lower().endswith("options"):
            if module == "Options":
                mod = self.options_module
            else:
                mod = importlib.import_module(module)
            obj = getattr(mod, name)
            if issubclass(obj, (self.options_module.Option, self.options_module.PlandoConnection,
                                self.options_module.PlandoItem, self.options_module.PlandoText)):
                return obj

        raise pickle.UnpicklingError(f"global '{module}.{name}' is forbidden")


def restricted_loads(s: bytes) -> Any:

    return RestrictedUnpickler(io.BytesIO(s)).load()


def restricted_dumps(obj: Any) -> bytes:

    s = pickle.dumps(obj)

    try:
        restricted_loads(s)
    except pickle.UnpicklingError as e:
        raise pickle.PicklingError(e) from e

    return s


class ByValue:
    __doc__ = '\n    Mixin for enums to pickle value instead of name (restores pre-3.11 behavior). Use as left-most parent.\n    See https://github.com/python/cpython/pull/26658 for why this exists.\n    '
    def __reduce_ex__(self, prot):
        return self.__class__, (self._value_, )


class KeyedDefaultDict(collections.defaultdict):
    __doc__ = 'defaultdict variant that uses the missing key as argument to default_factory'
    default_factory: typing.Callable[[typing.Any], typing.Any]

    def __init__(self,
                 default_factory: typing.Callable[[Any], Any] = None,
                 seq: typing.Union[typing.Mapping, typing.Iterable, None] = None,
                 **kwargs):
        if seq is not None:
            super().__init__(default_factory, seq, **kwargs)
        else:
            super().__init__(default_factory, **kwargs)

    def __missing__(self, key):
        self[key] = value = self.default_factory(key)
        return value


def get_text_between(text: str, start: str, end: str) -> str:
    return text[text.index(start) + len(start): text.rindex(end)]


def get_text_after(text: str, start: str) -> str:
    return text[text.index(start) + len(start):]


loglevel_mapping = {'error': logging.ERROR, 'info': logging.INFO, 'warning': logging.WARNING, 'debug': logging.DEBUG}


def init_logging(name: str, loglevel: typing.Union[str, int] = logging.INFO,
                 write_mode: str = "w", log_format: str = "[%(name)s at %(asctime)s]: %(message)s",
                 add_timestamp: bool = False, exception_logger: typing.Optional[str] = None):
    import datetime
    loglevel: int = loglevel_mapping.get(loglevel, loglevel)
    log_folder = user_path("logs")
    os.makedirs(log_folder, exist_ok=True)
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()
    root_logger.setLevel(loglevel)
    logging.getLogger("websockets").setLevel(loglevel)
    if "a" not in write_mode:
        name += f"_{datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S')}"
    file_handler = logging.FileHandler(
        os.path.join(log_folder, f"{name}.txt"),
        write_mode,
        encoding="utf-8-sig")
    file_handler.setFormatter(logging.Formatter(log_format))

    class Filter(logging.Filter):
        def __init__(self, filter_name: str, condition: typing.Callable[[logging.LogRecord], bool]) -> None:
            super().__init__(filter_name)
            self.condition = condition

        def filter(self, record: logging.LogRecord) -> bool:
            return self.condition(record)

    file_handler.addFilter(Filter("NoStream", lambda record: not getattr(record, "NoFile", False)))
    file_handler.addFilter(Filter("NoCarriageReturn", lambda record: '\r' not in record.getMessage()))
    root_logger.addHandler(file_handler)
    if sys.stdout:
        formatter = logging.Formatter(fmt='[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.addFilter(Filter("NoFile", lambda record: not getattr(record, "NoStream", False)))
        if add_timestamp:
            stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")


    if not getattr(sys.excepthook, "_wrapped", False):
        orig_hook = sys.excepthook

        def handle_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            logging.getLogger(exception_logger).exception("Uncaught exception",
                                                          exc_info=(exc_type, exc_value, exc_traceback),
                                                          extra={"NoStream": exception_logger is None})
            return orig_hook(exc_type, exc_value, exc_traceback)

        handle_exception._wrapped = True

        sys.excepthook = handle_exception

    def _cleanup():
        for file in os.scandir(log_folder):
            if file.name.endswith(".txt"):
                last_change = datetime.datetime.fromtimestamp(file.stat().st_mtime)
                if datetime.datetime.now() - last_change > datetime.timedelta(days=7):
                    try:
                        os.unlink(file.path)
                    except Exception as e:
                        logging.exception(e)
                    else:
                        logging.debug(f"Deleted old logfile {file.path}")
    import threading
    threading.Thread(target=_cleanup, name="LogCleaner").start()
    import platform
    logging.info(
        f"Archipelago ({__version__}) logging initialized"
        f" on {platform.platform()} process {os.getpid()}"
        f" running Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        f"{' (frozen)' if is_frozen() else ''}"
    )


def stream_input(stream: typing.TextIO, queue: "asyncio.Queue[str]"):
    def queuer():
        while 1:
            try:
                text = stream.readline().strip()
            except UnicodeDecodeError as e:
                logging.exception(e)
            else:
                if text:
                    queue.put_nowait(text)
                else:
                    sleep(0.01)

    from threading import Thread
    thread = Thread(target=queuer, name=f"Stream handler for {stream.name}", daemon=True)
    thread.start()
    return thread


def tkinter_center_window(window: "tkinter.Tk") -> None:
    window.update()
    x = int(window.winfo_screenwidth() / 2 - window.winfo_reqwidth() / 2)
    y = int(window.winfo_screenheight() / 2 - window.winfo_reqheight() / 2)
    window.geometry(f"+{x}+{y}")


class VersionException(Exception):
    pass


def chaining_prefix(index: int, labels: typing.Sequence[str]) -> str:
    text = ""
    max_label = len(labels) - 1
    while index > max_label:
        text += labels[-1]
        index -= max_label
    return labels[index] + text


def format_SI_prefix(value, power=1000, power_labels=("", "k", "M", "G", "T", "P", "E", "Z", "Y")) -> str:

    import decimal
    n = 0
    value = decimal.Decimal(value)
    limit = power - decimal.Decimal("0.005")
    while value >= limit:
        value /= power
        n += 1

    return f"{value.quantize(decimal.Decimal('1.00'))} {chaining_prefix(n, power_labels)}"


def get_fuzzy_results(input_word: str, word_list: typing.Collection[str], limit: typing.Optional[int] = None) \
        -> typing.List[typing.Tuple[str, int]]:
    import jellyfish

    def get_fuzzy_ratio(word1: str, word2: str) -> float:
        if word1 == word2:
            return 1.01
        return (1 - jellyfish.damerau_levenshtein_distance(word1.lower(), word2.lower())
                / max(len(word1), len(word2)))

    limit = limit if limit else len(word_list)
    return list(
        map(
            lambda container: (container[0], int(container[1]*100)),
            sorted(
                map(lambda candidate: (candidate, get_fuzzy_ratio(input_word, candidate)), word_list),
                key=lambda element: element[1],
                reverse=True
            )[0:limit]
        )
    )


def get_intended_text(input_text: str, possible_answers) -> typing.Tuple[str, bool, str]:
    picks = get_fuzzy_results(input_text, possible_answers, limit=2)
    if len(picks) > 1:
        dif = picks[0][1] - picks[1][1]
        if picks[0][1] == 101:
            return picks[0][0], True, "Perfect Match"
        elif picks[0][1] == 100:
            return picks[0][0], True, "Case Insensitive Perfect Match"
        elif picks[0][1] < 75:
            return picks[0][0], False, f"Didn't find something that closely matches '{input_text}', " \
                                       f"did you mean '{picks[0][0]}'? ({picks[0][1]}% sure)"
        elif dif > 5:
            return picks[0][0], True, "Close Match"
        else:
            return picks[0][0], False, f"Too many close matches for '{input_text}', " \
                                       f"did you mean '{picks[0][0]}'? ({picks[0][1]}% sure)"
    else:
        if picks[0][1] > 90:
            return picks[0][0], True, "Only Option Match"
        else:
            return picks[0][0], False, f"Didn't find something that closely matches '{input_text}', " \
                                       f"did you mean '{picks[0][0]}'? ({picks[0][1]}% sure)"


def get_input_text_from_response(text: str, command: str) -> typing.Optional[str]:

    if "did you mean " in text:
        for question in ("Didn't find something that closely matches",
                         "Too many close matches"):
            if text.startswith(question):
                name = get_text_between(text, "did you mean '",
                                        "'? (")
                return f"{command} {name}"
    elif text.startswith("Missing: "):
        return text.replace("Missing: ", "!hint_location ")
    return None


def is_kivy_running() -> bool:
    if "kivy" in sys.modules:
        from kivy.app import App
        return App.get_running_app() is not None
    return False


def env_cleared_lib_path() -> Mapping[str, str]:

    env = os.environ
    if "LD_LIBRARY_PATH" in env:
        env = env.copy()
        del env["LD_LIBRARY_PATH"]

    return env


def run_in_terminal(exe: Sequence[str]) -> bool:

    if is_windows:

        subprocess.Popen(["start", "Running Archipelago", *exe], shell=True)
        return True
    elif is_linux:


        legacy_terminals = ("x-terminal-emulator", "konsole", "alacritty", "kitty")
        modern_terminals = ("gnome-terminal", "cosmic-term", "ptyxis")

        terminal: str | None = None
        for term in itertools.chain(legacy_terminals, modern_terminals, ("xterm",)):
            terminal = which(term)
            if terminal:
                break

        if terminal:

            ld_lib_path = os.environ.get("LD_LIBRARY_PATH")
            lib_path_setter = f"env LD_LIBRARY_PATH={shlex.quote(ld_lib_path)} " if ld_lib_path else ""
            env = env_cleared_lib_path()

            real_terminal_name = pathlib.Path(terminal).resolve().name
            if real_terminal_name in modern_terminals:
                subprocess.Popen([terminal, "--", "sh", "-c", lib_path_setter + shlex.join(exe)], env=env)
            else:
                subprocess.Popen([terminal, "-e", "sh", "-c", lib_path_setter + shlex.join(exe)], env=env)
            return True
    elif is_macos:
        terminal = [which("open"), "-W", "-a", "Terminal.app"]
        subprocess.Popen([*terminal, *exe])
        return True
    return False


def _mp_open_filename(res: "multiprocessing.Queue[typing.Optional[str]]", *args: Any) -> None:
    if is_kivy_running():
        raise RuntimeError("kivy should not be running in multiprocess")
    res.put(open_filename(*args))


def _mp_save_filename(res: "multiprocessing.Queue[typing.Optional[str]]", *args: Any) -> None:
    if is_kivy_running():
        raise RuntimeError("kivy should not be running in multiprocess")
    res.put(save_filename(*args))

def _run_for_stdout(*args: str):
    env = env_cleared_lib_path()
    return subprocess.run(args, capture_output=True, text=True, env=env).stdout.split("\n", 1)[0] or None


def open_filename(title: str, filetypes: typing.Iterable[typing.Tuple[str, typing.Iterable[str]]], suggest: str = "") \
        -> typing.Optional[str]:
    logging.info(f"Opening file input dialog for {title}.")

    if is_linux:

        from shutil import which
        kdialog = which("kdialog")
        if kdialog:
            k_filters = '|'.join((f'{text} (*{" *".join(ext)})' for (text, ext) in filetypes))
            return _run_for_stdout(kdialog, f"--title={title}", "--getopenfilename", suggest or ".", k_filters)
        zenity = which("zenity")
        if zenity:
            z_filters = (f'--file-filter={text} ({", ".join(ext)}) | *{" *".join(ext)}' for (text, ext) in filetypes)
            selection = (f"--filename={suggest}",) if suggest else ()
            return _run_for_stdout(zenity, f"--title={title}", "--file-selection", *z_filters, *selection)


    try:
        import tkinter
        import tkinter.filedialog
    except Exception as e:
        logging.error('Could not load tkinter, which is likely not installed. '
                      f'This attempt was made because open_filename was used for "{title}".')
        raise e
    else:
        if is_macos and is_kivy_running():


            from multiprocessing import Process, Queue
            res: "Queue[typing.Optional[str]]" = Queue()
            Process(target=_mp_open_filename, args=(res, title, filetypes, suggest)).start()
            return res.get()
        try:
            root = tkinter.Tk()
        except tkinter.TclError:
            return None
        root.withdraw()
        try:
            return tkinter.filedialog.askopenfilename(
                title=title,
                filetypes=((t[0], ' '.join(t[1])) for t in filetypes),
                initialfile=suggest or None,
            )
        finally:
            root.destroy()


def save_filename(title: str, filetypes: typing.Iterable[typing.Tuple[str, typing.Iterable[str]]], suggest: str = "") \
        -> typing.Optional[str]:
    logging.info(f"Opening file save dialog for {title}.")

    if is_linux:

        from shutil import which
        kdialog = which("kdialog")
        if kdialog:
            k_filters = '|'.join((f'{text} (*{" *".join(ext)})' for (text, ext) in filetypes))
            return _run_for_stdout(kdialog, f"--title={title}", "--getsavefilename", suggest or ".", k_filters)
        zenity = which("zenity")
        if zenity:
            z_filters = (f'--file-filter={text} ({", ".join(ext)}) | *{" *".join(ext)}' for (text, ext) in filetypes)
            selection = (f"--filename={suggest}",) if suggest else ()
            return _run_for_stdout(zenity, f"--title={title}", "--file-selection", "--save", *z_filters, *selection)


    try:
        import tkinter
        import tkinter.filedialog
    except Exception as e:
        logging.error('Could not load tkinter, which is likely not installed. '
                      f'This attempt was made because save_filename was used for "{title}".')
        raise e
    else:
        if is_macos and is_kivy_running():


            from multiprocessing import Process, Queue
            res: "Queue[typing.Optional[str]]" = Queue()
            Process(target=_mp_save_filename, args=(res, title, filetypes, suggest)).start()
            return res.get()
        try:
            root = tkinter.Tk()
        except tkinter.TclError:
            return None
        root.withdraw()
        try:
            return tkinter.filedialog.asksaveasfilename(
                title=title,
                filetypes=((t[0], ' '.join(t[1])) for t in filetypes),
                initialfile=suggest or None,
            )
        finally:
            root.destroy()


def _mp_open_directory(res: "multiprocessing.Queue[typing.Optional[str]]", *args: Any) -> None:
    if is_kivy_running():
        raise RuntimeError("kivy should not be running in multiprocess")
    res.put(open_directory(*args))


def open_directory(title: str, suggest: str = "") -> typing.Optional[str]:
    if is_linux:

        from shutil import which
        kdialog = which("kdialog")
        if kdialog:
            return _run_for_stdout(kdialog, f"--title={title}", "--getexistingdirectory",
                       os.path.abspath(suggest) if suggest else ".")
        zenity = which("zenity")
        if zenity:
            z_filters = ("--directory",)
            selection = (f"--filename={os.path.abspath(suggest)}/",) if suggest else ()
            return _run_for_stdout(zenity, f"--title={title}", "--file-selection", *z_filters, *selection)


    try:
        import tkinter
        import tkinter.filedialog
    except Exception as e:
        logging.error('Could not load tkinter, which is likely not installed. '
                      f'This attempt was made because open_directory was used for "{title}".')
        raise e
    else:
        if is_macos and is_kivy_running():


            from multiprocessing import Process, Queue
            res: "Queue[typing.Optional[str]]" = Queue()
            Process(target=_mp_open_directory, args=(res, title, suggest)).start()
            return res.get()
        try:
            root = tkinter.Tk()
        except tkinter.TclError:
            return None
        root.withdraw()
        return tkinter.filedialog.askdirectory(title=title, mustexist=True, initialdir=suggest or None)


def messagebox(title: str, text: str, error: bool = False) -> None:
    if not gui_enabled:
        if error:
            logging.error(f"{title}: {text}")
        else:
            logging.info(f"{title}: {text}")
        return

    if is_kivy_running():
        from kvui import MessageBox
        MessageBox(title, text, error).open()
        return

    if is_linux and "tkinter" not in sys.modules:

        from shutil import which
        kdialog = which("kdialog")
        if kdialog:
            return _run_for_stdout(kdialog, f"--title={title}", "--error" if error else "--msgbox", text)
        zenity = which("zenity")
        if zenity:
            return _run_for_stdout(zenity, f"--title={title}", f"--text={text}", "--error" if error else "--info")

    elif is_windows:
        import ctypes
        style = 0x10 if error else 0x0
        return ctypes.windll.user32.MessageBoxW(0, text, title, style)


    try:
        import tkinter
        from tkinter.messagebox import showerror, showinfo
    except Exception as e:
        logging.error('Could not load tkinter, which is likely not installed. '
                      f'This attempt was made because messagebox was used for "{title}".')
        raise e
    else:
        root = tkinter.Tk()
        root.withdraw()
        showerror(title, text) if error else showinfo(title, text)
        root.update()


gui_enabled = not sys.stdout or "--nogui" not in sys.argv

def title_sorted(data: typing.Iterable, key=None, ignore: typing.AbstractSet[str] = frozenset(("a", "the"))):

    def sorter(element: Union[str, Dict[str, Any]]) -> str:
        if (not isinstance(element, str)):
            element = element["title"]

        parts = element.split(maxsplit=1)
        if parts[0].lower() in ignore:
            return parts[1].lower()
        else:
            return element.lower()
    return sorted(data, key=lambda i: sorter(key(i)) if key else sorter(i))


def read_snes_rom(stream: BinaryIO, strip_header: bool = True) -> bytearray:

    buffer = bytearray(stream.read())
    if strip_header and len(buffer) % 0x400 == 0x200:
        return buffer[0x200:]
    return buffer


_faf_tasks: "Set[asyncio.Task[typing.Any]]" = set()


def async_start(co: Coroutine[None, None, typing.Any], name: Optional[str] = None) -> None:


    task: asyncio.Task[typing.Any] = asyncio.create_task(co, name=name)
    _faf_tasks.add(task)
    task.add_done_callback(_faf_tasks.discard)


def deprecate(message: str, add_stacklevels: int = 0):

    if __debug__:
        raise Exception(message)
    warnings.warn(message, stacklevel=2 + add_stacklevels)


def _extend_freeze_support() -> None:


    import multiprocessing
    import multiprocessing.spawn

    def _freeze_support() -> None:

        from subprocess import _args_from_interpreter_flags


        multiprocessing.process.ORIGINAL_DIR = None


        if (
            len(sys.argv) >= 2 and sys.argv[-2] == '-c' and sys.argv[-1].startswith((
                'from multiprocessing.resource_tracker import main',
                'from multiprocessing.forkserver import main'
            )) and set(sys.argv[1:-2]) == set(_args_from_interpreter_flags())
        ):
            exec(sys.argv[-1])
            sys.exit()


        if multiprocessing.spawn.is_forking(sys.argv):
            kwargs = {}
            for arg in sys.argv[2:]:
                name, value = arg.split('=')
                if value == 'None':
                    kwargs[name] = None
                else:
                    kwargs[name] = int(value)
            multiprocessing.spawn.spawn_main(**kwargs)
            sys.exit()

    def _noop() -> None:
        pass

    multiprocessing.freeze_support = multiprocessing.spawn.freeze_support = _freeze_support if is_frozen() else _noop


@deprecated("Use multiprocessing.freeze_support() instead")
def freeze_support() -> None:

    import multiprocessing

    deprecate("Use multiprocessing.freeze_support() instead")
    multiprocessing.freeze_support()


_extend_freeze_support()


def visualize_regions(
        root_region: Region,
        file_name: str,
        *,
        show_entrance_names: bool = False,
        show_entrance_rules: bool = False,
        show_locations: bool = True,
        show_other_regions: bool = True,
        linetype_ortho: bool = True,
        regions_to_highlight: set[Region] | None = None,
        entrance_highlighting: dict[int, int] | None = None,
        detail_other_regions: bool = False,
        auto_assign_colors: bool = False) -> None:

    if regions_to_highlight is None:
        regions_to_highlight = set()
    assert root_region.multiworld, "The multiworld attribute of root_region has to be filled"
    from BaseClasses import Entrance, Item, Location, LocationProgressType, MultiWorld, Region
    from collections import deque
    import re

    uml: typing.List[str] = list()
    seen: typing.Set[Region] = set()
    regions: typing.Deque[Region] = deque((root_region,))
    multiworld: MultiWorld = root_region.multiworld

    colors_used: set[int] = set()
    if entrance_highlighting:
        for color in entrance_highlighting.values():

            colors_used.add(color & 0xF0F0F0)
    else:


        entrance_highlighting = {}

    def select_color(group: int) -> int:


        COLOR_INDEX_SPACING: int = 0x357
        new_color_index: int = (group * COLOR_INDEX_SPACING) % 0x1000
        new_color = ((new_color_index & 0xF00) << 12) + \
                    ((new_color_index & 0xF0) << 8) + \
                    ((new_color_index & 0xF) << 4)
        while new_color in colors_used:


            new_color_index += COLOR_INDEX_SPACING
            new_color = ((new_color_index & 0xF00) << 12) + \
                        ((new_color_index & 0xF0) << 8) + \
                        ((new_color_index & 0xF) << 4)
        return new_color

    def fmt(obj: Union[Entrance, Item, Location, Region]) -> str:
        name = obj.name
        if isinstance(obj, Item):
            name = multiworld.get_name_string_for_object(obj)
            if obj.advancement:
                name = f"**{name}**"
            if obj.code is None:
                name = f"//{name}//"
        if isinstance(obj, Location):
            if obj.progress_type == LocationProgressType.PRIORITY:
                name = f"**{name}**"
            elif obj.progress_type == LocationProgressType.EXCLUDED:
                name = f"--{name}--"
            if obj.address is None:
                name = f"//{name}//"
        return re.sub("[\".:]", "", name)

    def visualize_exits(region: Region) -> None:
        import rule_builder.rules
        for exit_ in region.exits:
            color_code: str = ""
            if exit_.randomization_group in entrance_highlighting:
                color_code = f" #{entrance_highlighting[exit_.randomization_group]:0>6X}"
            if exit_.connected_region:
                label = ""
                if show_entrance_names:
                    label += fmt(exit_)
                if show_entrance_rules:
                    if isinstance(exit_.access_rule, rule_builder.rules.Rule.Resolved):
                        if label:
                            label += "\\n"
                        label += exit_.access_rule.explain_str()
                if label:
                    uml.append(f"\"{fmt(region)}\" --> \"{fmt(exit_.connected_region)}\" : \"{label}\"{color_code}")
                else:
                    try:
                        uml.remove(f"\"{fmt(exit_.connected_region)}\" --> \"{fmt(region)}\"{color_code}")
                        uml.append(f"\"{fmt(exit_.connected_region)}\" <--> \"{fmt(region)}\"{color_code}")
                    except ValueError:
                        uml.append(f"\"{fmt(region)}\" --> \"{fmt(exit_.connected_region)}\"{color_code}")
            else:
                uml.append(f"circle \"unconnected exit:\\n{fmt(exit_)}\" {color_code}")
                uml.append(f"\"{fmt(region)}\" --> \"unconnected exit:\\n{fmt(exit_)}\"{color_code}")
        for entrance in region.entrances:
            color_code: str = ""
            if entrance.randomization_group in entrance_highlighting:
                color_code = f" #{entrance_highlighting[entrance.randomization_group]:0>6X}"
            if not entrance.parent_region:
                uml.append(f"circle \"unconnected entrance:\\n{fmt(entrance)}\"{color_code}")
                uml.append(f"\"unconnected entrance:\\n{fmt(entrance)}\" --> \"{fmt(region)}\"{color_code}")

    def visualize_locations(region: Region) -> None:
        any_lock = any(location.locked for location in region.locations)
        for location in region.locations:
            lock = "<&lock-locked> " if location.locked else "<&lock-unlocked,color=transparent> " if any_lock else ""
            if location.item:
                uml.append(f"\"{fmt(region)}\" : {{method}} {lock}{fmt(location)}: {fmt(location.item)}")
            else:
                uml.append(f"\"{fmt(region)}\" : {{field}} {lock}{fmt(location)}")

    def visualize_region(region: Region) -> None:
        uml.append(f"class \"{fmt(region)}\" {'#00FF00' if region in regions_to_highlight else ''}")
        if show_locations:
            visualize_locations(region)
        visualize_exits(region)

    def visualize_other_regions() -> None:
        if other_regions := [region for region in multiworld.get_regions(root_region.player) if region not in seen]:
            uml.append("package \"other regions\" <<Cloud>> {")
            for region in other_regions:
                if detail_other_regions:
                    visualize_region(region)
                else:
                    uml.append(f"class \"{fmt(region)}\"")
            uml.append("}")

    if auto_assign_colors:
        all_entrances: list[Entrance] = []
        for region in multiworld.get_regions(root_region.player):
            all_entrances.extend(region.entrances)
            all_entrances.extend(region.exits)
        all_groups: list[int] = sorted(set([entrance.randomization_group for entrance in all_entrances]))
        for group in all_groups:
            if group not in entrance_highlighting:
                if len(colors_used) >= 0x1000:

                    break
                new_color: int = select_color(group)
                entrance_highlighting[group] = new_color
                colors_used.add(new_color)

    uml.append("@startuml")
    uml.append("hide circle")
    uml.append("hide empty members")
    if linetype_ortho:
        uml.append("skinparam linetype ortho")
    while regions:
        if (current_region := regions.popleft()) not in seen:
            seen.add(current_region)
            visualize_region(current_region)
            regions.extend(exit_.connected_region for exit_ in current_region.exits if exit_.connected_region)
    if show_other_regions or detail_other_regions:
        visualize_other_regions()
    uml.append("@enduml")

    with open(file_name, "wt", encoding="utf-8") as f:
        f.write("\n".join(uml))


_T_co = TypeVar("_T_co", covariant=True)


class RepeatableChain(Generic[_T_co]):
    def __init__(self, iterable: Iterable[Collection[_T_co]]):
        self.iterable = iterable

    def __iter__(self):
        return itertools.chain.from_iterable(self.iterable)

    def __bool__(self):
        return any(sub_iterable for sub_iterable in self.iterable)

    def __len__(self):
        return sum(len(iterable) for iterable in self.iterable)

    def __contains__(self, o: object) -> bool:
        return any(o in sub_iterable for sub_iterable in self.iterable)


def is_iterable_except_str(obj: object) -> TypeGuard[typing.Iterable[typing.Any]]:

    if isinstance(obj, str):
        return False
    return isinstance(obj, typing.Iterable)


def utcnow() -> datetime:

    return datetime.now(timezone.utc).replace(tzinfo=None)


class DaemonThreadPoolExecutor(concurrent.futures.ThreadPoolExecutor):
    __doc__ = '\n    ThreadPoolExecutor that uses daemonic threads that do not keep the program alive.\n    NOTE: use this with caution because killed threads will not properly clean up.\n    '

    def _adjust_thread_count(self):

        import threading
        import weakref
        from concurrent.futures.thread import _worker

        if self._idle_semaphore.acquire(timeout=0):
            return

        def weakref_cb(_, q=self._work_queue):
            q.put(None)

        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = f"{self._thread_name_prefix or self}_{num_threads}"
            t = threading.Thread(
                name=thread_name,
                target=_worker,
                args=(
                    weakref.ref(self, weakref_cb),
                    self._work_queue,
                    self._initializer,
                    self._initargs,
                ),
                daemon=True,
            )
            t.start()
            self._threads.add(t)


def get_full_typename(t: type) -> str:

    module = t.__module__
    if module and module != "builtins":
        return f"{module}.{t.__qualname__}"
    return t.__qualname__


def get_all_causes(ex: Exception) -> str:

    cause = ex
    causes = [f"{get_full_typename(type(ex))}: {ex}"]
    while cause := cause.__cause__:
        causes.append(f"{get_full_typename(type(cause))}: {cause}")
    top = causes[-1]
    others = "".join(f"\n{' ' * (i + 1)}Which caused: {c}" for i, c in enumerate(reversed(causes[:-1])))
    return f"{top}{others}"


_empty_frozenset = frozenset()


def empty_frozenset_factory() -> frozenset:

    return _empty_frozenset
