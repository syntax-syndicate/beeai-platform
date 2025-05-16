def import_repositories():
    """Import all repositories to make sure they are registered into sqlalchemy metadata"""
    import importlib
    import pkgutil

    for _, name, _ in pkgutil.walk_packages(__path__):
        importlib.import_module(f"{__name__}.{name}")
        print(f"{__name__}.{name}")


import_repositories()
