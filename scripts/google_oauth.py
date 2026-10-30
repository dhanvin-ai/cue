"""Operator runs Google OAuth consent for one mailbox and stores the grant as a local secret.

Needs a Google Cloud OAuth client of type "Desktop app" with the Gmail and Calendar APIs enabled.
The grant covers both connectors; bind each afterwards with the printed commands.

Usage: python scripts/google_oauth.py CLIENT_SECRET_JSON owner@example.com
"""

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import time
import urllib.parse
import webbrowser

import httpx

from cue.connectors.secret_store import FileSecretStore

SCOPES = ("https://www.googleapis.com/auth/gmail.modify",
          "https://www.googleapis.com/auth/calendar")


def consent(client_id: str, client_secret: str, email: str) -> dict:
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(16)
    received: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            received.update({key: values[0] for key, values in query.items()})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Cue received the Google grant. You can close this tab.")

        def log_message(self, *args):
            return None

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_port}"
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent",
        "login_hint": email, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    print("Opening consent screen. If no browser opens, visit:\n" + url)
    webbrowser.open(url)
    while "code" not in received and "error" not in received:
        server.handle_request()
    if received.get("state") != state or "code" not in received:
        raise SystemExit(f"Consent failed: {received.get('error', 'state mismatch')}")
    response = httpx.post("https://oauth2.googleapis.com/token", data={
        "grant_type": "authorization_code", "code": received["code"],
        "redirect_uri": redirect, "client_id": client_id, "client_secret": client_secret,
        "code_verifier": verifier,
    }, timeout=15)
    response.raise_for_status()
    token = response.json()
    if not token.get("refresh_token"):
        raise SystemExit("Google returned no refresh token; revoke the app and retry")
    return {"access_token": token["access_token"], "refresh_token": token["refresh_token"],
            "client_id": client_id, "client_secret": client_secret,
            "expires_at": time.time() + int(token["expires_in"])}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("client_secret_json", help="Downloaded OAuth client JSON (Desktop app)")
    parser.add_argument("email")
    args = parser.parse_args()
    with open(args.client_secret_json, encoding="utf-8") as handle:
        client = json.load(handle)["installed"]
    grant = consent(client["client_id"], client["client_secret"], args.email)
    name = "google-" + "".join(ch if ch.isalnum() else "-" for ch in args.email.casefold())
    ref = FileSecretStore().write(name, json.dumps(grant).encode())
    print(f"Stored {ref}\nBind with:")
    for provider in ("gmail", "calendar"):
        print(f"  python scripts/bind_source.py TENANT_UUID {provider} {args.email} {ref} "
              "--no-subscribe")


if __name__ == "__main__":
    main()
