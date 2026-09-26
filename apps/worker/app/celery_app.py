from __future__ import annotations

import os

from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery(
    "radbrain",
    broker=redis_url,
    include=[
        "apps.worker.app.tasks",
        "apps.worker.app.reminders",
        "apps.worker.app.knowledge.tasks",
        "apps.worker.app.datarights.tasks",
    ],
)
celery_app.conf.update(
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_serializer="json",
    task_track_started=True,
    timezone="UTC",
    worker_prefetch_multiplier=1,
    beat_schedule={
        "study-reminders": {"task": "radbrain.send_due_reminders", "schedule": 300.0},
        "expire-data-exports": {"task": "radbrain.expire_data_exports", "schedule": 3600.0},
    },
)
