"""Load local .env values before tests import app code.

No-op when the .env file is absent, so CI that sets environment variables
directly is unaffected. Existing environment variables always win.
"""

import os
from pathlib import Path

_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.is_file():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _, _value = _line.partition("=")
        os.environ.setdefault(_key.strip(), _value.strip())

# Tests exercise real Firebase verification via monkeypatched tokens, so the
# local dev auth bypass must never be active under pytest, even when .env sets it. Memory tests
# bring their own fake embedders, so a local keyword-only setting must not switch vectors off.
for _key in ("CUE_DEV_AUTH_UID", "CUE_DEV_TENANT_ID", "CUE_VECTOR_SEARCH", "CUE_TRANSCRIBER", "CUE_TTS"):
    os.environ.pop(_key, None)
