from datetime import datetime

from pydantic import BaseModel


class AlertResponse(BaseModel):
    alert_id: str
    watch_id: str
    rule_type: str
    triggered_at: datetime
    price: float | None
    offer: dict | None
    channel: str
    status: str
    error: str | None
