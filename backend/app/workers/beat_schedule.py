from celery.schedules import crontab

# SPEC.md §4.2 — both tasks run every hour at :00.
# fan_out_polls decides internally which watches are actually due based on plan interval.
# send_digests filters by rule.digest_time == current hour.

BEAT_SCHEDULE: dict = {
    "fan_out_polls": {
        "task": "app.workers.tasks.fan_out_polls",
        "schedule": crontab(minute=0),
    },
    "send_digests": {
        "task": "app.workers.tasks.send_digests",
        "schedule": crontab(minute=0),
    },
}
