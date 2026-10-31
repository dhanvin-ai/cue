"""One-time Google consent so the Meet CUE demo can create Meet links as Cue's own account.

Needs an OAuth client of type "Desktop app" from a Google Cloud project with the Calendar API
enabled (download its client_secret JSON). The consent page opens in Cue's bot Chrome profile,
so the dedicated account that is already signed in there is the one that grants access. A person
clicks through the consent screen; this script never sees a password.

    .venv/bin/python scripts/demo_google_auth.py --client-secrets ~/Downloads/client_secret_XXX.json

The refresh token is written to CUE_DEMO_GOOGLE_TOKEN_FILE (default ~/.cue-demo/google-oauth.json,
mode 0600). Scope is calendar.events only.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from cue.demo.config import settings  # noqa: E402
from cue.demo.google_calendar import SCOPE, TOKEN_URL, write_private  # noqa: E402

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--client-secrets", type=Path, required=True, help="Desktop-app OAuth client JSON from Google Cloud")
    parser.add_argument("--token-file", type=Path, default=settings.google_token_file)
    parser.add_argument("--profile", type=Path, default=settings.bot_profile, help="Chrome profile signed in as Cue")
    parser.add_argument("--default-browser", action="store_true", help="open in your default browser instead")
    args = parser.parse_args()

    raw = json.loads(args.client_secrets.read_text())
    client = raw.get("installed") or raw.get("web") or raw
    client_id, client_secret = client["client_id"], client["client_secret"]

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    result: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if query.get("state", [None])[0] != state:
                self.send_response(400)
                self.end_headers()
                return
            result["code"] = query.get("code", [None])[0]
            result["error"] = query.get("error", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<p style='font:16px system-ui'>Cue is connected. You can close this window.</p>")

        def log_message(self, *_):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_port}/"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    threading.Thread(target=server.handle_request, daemon=True).start()

    from face_bot import chrome_binary, profile_in_use

    binary = chrome_binary()
    if args.default_browser or not binary:
        print("Opening the consent page in your default browser. Sign in as Cue's dedicated account.")
        webbrowser.open(url)
    else:
        if pid := profile_in_use(args.profile):
            print(f"Chrome (pid {pid}) is using Cue's profile; quit it first.", file=sys.stderr)
            return 2
        print("Opening the consent page in Cue's Chrome profile. Approve access, then quit that Chrome.")
        subprocess.Popen([binary, f"--user-data-dir={args.profile}", "--no-first-run", "--no-default-browser-check", url])

    deadline = time.time() + 600
    while time.time() < deadline and not result:
        time.sleep(0.3)
    server.server_close()
    if not result.get("code"):
        print(f"No authorization received ({result.get('error') or 'timed out'}).", file=sys.stderr)
        return 1

    response = httpx.post(TOKEN_URL, data={
        "grant_type": "authorization_code", "code": result["code"], "redirect_uri": redirect,
        "client_id": client_id, "client_secret": client_secret, "code_verifier": verifier,
    }, timeout=20)
    if response.status_code != 200:
        print(f"Token exchange failed: {response.status_code} {response.text[:200]}", file=sys.stderr)
        return 1
    tokens = response.json()
    if not tokens.get("refresh_token"):
        print("Google returned no refresh token; remove Cue's prior grant at myaccount.google.com/permissions and retry.", file=sys.stderr)
        return 1
    me = httpx.get(
        "https://www.googleapis.com/calendar/v3/calendars/primary",
        headers={"Authorization": f"Bearer {tokens['access_token']}"}, timeout=20,
    )
    account = me.json().get("id") if me.status_code == 200 else None
    write_private(args.token_file, {
        "client_id": client_id, "client_secret": client_secret, "refresh_token": tokens["refresh_token"],
        "access_token": tokens["access_token"], "expires_at": time.time() + int(tokens.get("expires_in", 3600)),
        "account": account, "scope": tokens.get("scope"),
    })
    print(f"Saved Cue's Google credential for {account or 'the account'} to {args.token_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
