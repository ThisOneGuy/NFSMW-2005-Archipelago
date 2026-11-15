from pathlib import Path
import os
import shutil
import subprocess


def game_command(game, documents, environment):
    game = Path(game)
    if os.name == "nt":
        return [str(game)], environment
    wine = shutil.which("wine")
    winepath = shutil.which("winepath")
    if not wine or not winepath:
        raise RuntimeError(
            "Install Wine or Proton with wine and winepath available, then select the Windows speed.exe. The game still requires an ASI loader in the same Wine prefix."
        )
    environment = dict(environment)
    result = subprocess.run(
        [winepath, "-w", str(documents)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    path = result.stdout.strip()
    if not path:
        raise RuntimeError("Wine could not convert the isolated save folder.")
    environment["NFSMW_AP_DOCUMENTS_ROOT"] = path
    if environment.get("NFSMW_AP_PREFERENCES_PATH"):
        converted = subprocess.run(
            [winepath, "-w", environment["NFSMW_AP_PREFERENCES_PATH"]],
            env=environment, capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
        if not converted:
            raise RuntimeError("Wine could not convert the player preferences path.")
        environment["NFSMW_AP_PREFERENCES_PATH"] = converted
    overrides = environment.get("WINEDLLOVERRIDES", "")
    if "dinput8" not in overrides.casefold():
        environment["WINEDLLOVERRIDES"] = overrides + (";" if overrides else "") + "dinput8=n,b"
    return [wine, str(game)], environment


def configuration_path(text):
    if os.name == "nt":
        return text
    variables = {"USERPROFILE": str(Path.home()), "LOCALAPPDATA": str(Path.home() / ".local/share")}
    for name, value in variables.items():
        text = text.replace("%" + name + "%", value)
    return os.path.expandvars(text).replace("\\", "/")
