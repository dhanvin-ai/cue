"""One TLS context for every outbound client.

Building an httpx client loads the system CA store, which costs ~0.5 s on Windows. Clients
are made per request in several places, so they share this context instead of paying that
on every webhook and every memory lookup.
"""

import ssl
from functools import lru_cache


@lru_cache(maxsize=1)
def tls_context() -> ssl.SSLContext:
    return ssl.create_default_context()
