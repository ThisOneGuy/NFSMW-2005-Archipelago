from pathlib import Path
import json
import sys

from NFSMW_RetiredFeatures import cleanup_retired_assets


def main():
    if len(sys.argv) != 2:
        return 2
    game = Path(sys.argv[1])
    try:
        result = cleanup_retired_assets(game)
    except Exception as exc:
        result = {"errors": [str(exc)], "removed_files": 0, "freed_bytes": 0, "skipped_links": []}
    report = game / "NFSMWClient_Data" / "retired_cleanup.json"
    try:
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return 1
    return int(bool(result["errors"] or result["skipped_links"]))


if __name__ == "__main__":
    raise SystemExit(main())
