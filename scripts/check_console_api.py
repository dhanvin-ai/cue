"""Local smoke check for the read endpoints the web console depends on."""

import json
import os

from fastapi.testclient import TestClient

from scripts._local_env import load_local_env

load_local_env()
from cue.main import app  # noqa: E402

TENANT = os.environ["CUE_DEV_TENANT_ID"]
client = TestClient(app)


def show(label, response):
    print(f"--- {label}: {response.status_code}")
    if response.status_code == 200:
        print(json.dumps(response.json(), indent=2, default=str)[:1600])
    else:
        print(response.text[:400])


show("tasks", client.get(f"/v1/tenants/{TENANT}/agent/tasks"))
show("approvals", client.get(f"/v1/tenants/{TENANT}/agent/approvals"))
show("proactive", client.get(f"/v1/tenants/{TENANT}/proactive"))
show("status", client.get(f"/v1/tenants/{TENANT}/status"))
show("me", client.get(f"/v1/tenants/{TENANT}/me"))
show("access-report", client.get(f"/v1/tenants/{TENANT}/admin/access-report"))
