from pathlib import Path


def runtime_development_file(path):
    parts = tuple(part.casefold() for part in Path(path).parts)
    if any(part.endswith(".dist-info") for part in parts) and Path(path).name.casefold() in (
        "record",
        "wheel",
        "installer",
        "requested",
        "top_level.txt",
        "direct_url.json",
    ):
        return True
    if "site-packages" in parts and Path(path).suffix.casefold() in (".c", ".h", ".pyi", ".typed"):
        return True
    if "runtime" not in parts:
        return False
    relative = parts[parts.index("runtime") :]
    return relative[:3] == ("runtime", "tcl", "nmake") or relative in (
        ("runtime", "tcl", "tclconfig.sh"),
        ("runtime", "tcl", "tclooconfig.sh"),
        ("runtime", "tcl", "tcl8", "8.5", "tcltest-2.5.8.tm"),
    )


def unnecessary_document(path):
    path = Path(path)
    if path.name.casefold() == "cmakelists.txt":
        return False
    if path.suffix.casefold() not in (".txt", ".md", ".rst", ".pdf", ".doc", ".docx", ".rtf"):
        return False
    if "licenses" in (part.casefold() for part in path.parts):
        return False
    return not path.name.upper().startswith(("LICENSE", "COPYING", "NOTICE", "AUTHORS"))


def ignored_data_files(root):
    root = Path(root).resolve()

    def ignore(directory, names):
        result = []
        for name in names:
            p = Path(directory).absolute() / name
            if (
                name
                in (
                    "__pycache__",
                    "user",
                    "retired_cleanup.json",
                    "install_status.json",
                    "NFSMW_RaceMap_Status.csv",
                    "BUNDLE_SOURCES.json",
                    "SOURCES.json",
                    "NATIVE_BUILD.json",
                )
                or name.casefold().startswith("readme")
                or unnecessary_document(p)
                or runtime_development_file(p.relative_to(root))
                or p.suffix.casefold()
                in (
                    ".pyc",
                    ".pyo",
                    ".log",
                    ".bak",
                    ".old",
                    ".tmp",
                    ".partial",
                    ".bat",
                    ".cmd",
                    ".pyi",
                    ".pdb",
                )
                or p.name == "tests"
            ):
                result.append(name)
        return result

    return ignore


def sanitize_runtime_archives(data):
    import zipfile

    removed = 0
    for path in (Path(data) / "runtime").rglob("*.zip"):
        with zipfile.ZipFile(path) as source:
            unwanted = {
                i.filename
                for i in source.infolist()
                if Path(i.filename).name.casefold().startswith("readme")
                or unnecessary_document(i.filename)
                or Path(i.filename).suffix.casefold()
                in (".bat", ".cmd", ".log", ".bak", ".old", ".tmp", ".pdb")
            }
            if not unwanted:
                continue
            temporary = path.with_suffix(".clean")
            with zipfile.ZipFile(temporary, "w") as destination:
                for entry in source.infolist():
                    if entry.filename not in unwanted:
                        destination.writestr(entry, source.read(entry))
        temporary.replace(path)
        removed += len(unwanted)
    return removed
