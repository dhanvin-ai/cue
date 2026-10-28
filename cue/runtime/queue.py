"""Task queue interface. Cloud Tasks in production, an in-memory queue locally."""

import os
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID


class Queue(Protocol):
    def enqueue(self, tenant_id: UUID, task_id: UUID, delay_seconds: int = 0) -> None: ...


class LocalQueue:
    """Deterministic queue for tests and local runs. Call `drain()` to execute."""

    def __init__(self):
        self.items: list[tuple[UUID, UUID, int]] = []

    def enqueue(self, tenant_id: UUID, task_id: UUID, delay_seconds: int = 0) -> None:
        self.items.append((tenant_id, task_id, delay_seconds))

    def drain(self) -> list[tuple[UUID, UUID, int]]:
        items, self.items = self.items, []
        return items


class CloudTasksQueue:
    """Pushes task IDs to a Cloud Tasks HTTP target that calls the runtime worker."""

    def __init__(self, project: str | None = None, location: str | None = None,
                 queue: str | None = None, target_url: str | None = None):
        from google.cloud import tasks_v2

        self._tasks = tasks_v2
        self.client = tasks_v2.CloudTasksClient()
        self.project = project or os.environ["GOOGLE_CLOUD_PROJECT"]
        self.location = location or os.environ["CLOUD_TASKS_LOCATION"]
        self.queue = queue or os.environ["CLOUD_TASKS_QUEUE"]
        self.target_url = target_url or os.environ["CLOUD_TASKS_TARGET_URL"]
        self.parent = self.client.queue_path(self.project, self.location, self.queue)

    def enqueue(self, tenant_id: UUID, task_id: UUID, delay_seconds: int = 0) -> None:
        from google.protobuf import timestamp_pb2

        task = {
            "http_request": {
                "http_method": self._tasks.HttpMethod.POST,
                "url": f"{self.target_url.rstrip('/')}/internal/tasks/{tenant_id}/{task_id}",
                "headers": {"Content-Type": "application/json"},
                "oidc_token": {"service_account_email": os.environ["CLOUD_TASKS_SERVICE_ACCOUNT"]},
            }
        }
        if delay_seconds:
            schedule = timestamp_pb2.Timestamp()
            schedule.FromDatetime(datetime.now(timezone.utc) + timedelta(seconds=delay_seconds))
            task["schedule_time"] = schedule
        self.client.create_task(parent=self.parent, task=task)
