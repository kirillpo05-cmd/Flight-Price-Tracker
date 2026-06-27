from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "farewatch",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)
celery_app.conf.timezone = "UTC"
celery_app.conf.enable_utc = True
