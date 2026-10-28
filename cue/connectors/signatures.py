import base64
import hashlib
import hmac
import json
import time
from collections.abc import Mapping


def slack(body: bytes, headers: Mapping[str, str], key: bytes) -> bool:
    try:
        timestamp = headers["x-slack-request-timestamp"]
        signature = headers["x-slack-signature"]
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except (KeyError, ValueError):
        return False
    expected = "v0=" + hmac.new(key, b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def linear(body: bytes, headers: Mapping[str, str], key: bytes) -> bool:
    try:
        timestamp = int(json.loads(body)["webhookTimestamp"])
        signature = headers["linear-signature"]
        if abs(time.time() * 1000 - timestamp) > 60_000:
            return False
    except (KeyError, ValueError, TypeError):
        return False
    expected = hmac.new(key, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def recall(body: bytes, headers: Mapping[str, str], key: bytes) -> bool:
    try:
        message_id = headers.get("webhook-id") or headers["svix-id"]
        timestamp = headers.get("webhook-timestamp") or headers["svix-timestamp"]
        signatures = headers.get("webhook-signature") or headers["svix-signature"]
        if abs(time.time() - int(timestamp)) > 300 or not key.startswith(b"whsec_"):
            return False
        signing_key = base64.b64decode(key[6:])
    except (KeyError, ValueError):
        return False
    expected = hmac.new(signing_key, message_id.encode() + b"." + timestamp.encode() + b"." + body, hashlib.sha256).digest()
    for candidate in signatures.split():
        version, _, encoded = candidate.partition(",")
        if version == "v1":
            try:
                if hmac.compare_digest(base64.b64decode(encoded), expected):
                    return True
            except ValueError:
                pass
    return False
