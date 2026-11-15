GAME = "Need for Speed: Most Wanted"


def register():
    from worlds.LauncherComponents import Component, Type, components
    from .launcher import launch_client

    current = next((c for c in components if c.display_name == "NFSMW Client"), None)
    if current is None:
        current = next((c for c in components if c.display_name == "NFSMW Client View"), None)
    if current is None:
        current = Component("NFSMW Client", component_type=Type.CLIENT)
        components.append(current)
    current.display_name = "NFSMW Client"
    current.type = Type.CLIENT
    current.game_name = GAME
    current.supports_uri = True
    current.func = launch_client
    current.cli = False
    current.description = ""

    for component in components:
        if component is not current and component.display_name in (
            "NFSMW Client",
            "NFSMW Client View",
        ):
            component.type = Type.HIDDEN
            component.supports_uri = False
            component.func = launch_client
    if not any(c.display_name == "NFSMW Client View" for c in components):
        components.append(
            Component("NFSMW Client View", component_type=Type.HIDDEN, func=launch_client)
        )
