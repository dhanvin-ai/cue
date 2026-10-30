"""Load local .env values for developer scripts.

No-op when the .env file is absent, so CI and deployed containers that inject
environment variables directly are unaffected. Existing environment variables
always win over .env values.
"""

import os
from pathlib import Path


def load_local_env() -> None:
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())
