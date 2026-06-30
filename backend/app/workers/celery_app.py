from celery import Celery

from app.core.config import settings
from app.workers.beat_schedule import BEAT_SCHEDULE

celery_app = Celery(
    "farewatch",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],  # auto-register tasks on worker start
)

celery_app.conf.timezone = "UTC"
celery_app.conf.enable_utc = True
celery_app.conf.beat_schedule = BEAT_SCHEDULE
