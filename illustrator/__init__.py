def main(*args, **kwargs):
    from .server import main as server_main

    return server_main(*args, **kwargs)


__all__ = ["main"]
