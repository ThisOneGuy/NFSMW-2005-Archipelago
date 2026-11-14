def run_client(url=None):
    from .viewer import ClientApp

    app = ClientApp(initial_url=url)
    url = None
    app.run()


def launch_client(*args):
    from worlds.LauncherComponents import launch_subprocess
    from .connection_links import parse_link

    url = next(
        (arg for arg in args if isinstance(arg, str) and arg.startswith("archipelago:")), None
    )
    if url:
        try:
            parse_link(url)
        except ValueError as exc:
            from Utils import messagebox

            messagebox("NFSMW Client", str(exc), error=True)
            return
    launch_subprocess(run_client, name="NFSMW Client", args=(url,))
