"""The library client, built in one place and only when a command needs it."""

import odouche


def open_client() -> odouche.Client:
    """Open the client on the session in use."""
    return odouche.Client()
