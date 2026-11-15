import os
from pathlib import Path


def desktop_state_directory():
    return (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "NFSMWArchipelago"
    )
