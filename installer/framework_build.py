from pathlib import Path


def framework_flags(reference, extra=()):
    if reference is None:
        raise ValueError("Supply the Microsoft .NET Framework 4.8 reference assembly directory.")
    reference = Path(reference).resolve()
    libraries = ("mscorlib.dll", "System.dll", "System.Core.dll", *extra)
    for name in libraries:
        if not (reference / name).is_file():
            raise FileNotFoundError(reference / name)
    return ["-noconfig", "-nostdlib+"] + ["-r:" + str(reference / name) for name in libraries]
