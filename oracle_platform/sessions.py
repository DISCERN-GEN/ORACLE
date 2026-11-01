from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from uuid import uuid4


class SessionState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(slots=True)
class PaperSession:
    session_id: str
    started_at: datetime
    ends_at: datetime
    state: SessionState = SessionState.RUNNING
    heartbeat_at: datetime | None = None
    observations: int = 0
    orders_submitted: int = 0
    errors: int = 0

    @classmethod
    def start(cls, hours: int = 12, now: datetime | None = None) -> "PaperSession":
        if hours <= 0 or hours > 24:
            raise ValueError("Session duration must be between 1 and 24 hours")
        now = now or datetime.now(timezone.utc)
        return cls(str(uuid4()), now, now + timedelta(hours=hours), heartbeat_at=now)

    def refresh(self, now: datetime | None = None) -> SessionState:
        now = now or datetime.now(timezone.utc)
        if self.state == SessionState.RUNNING:
            self.heartbeat_at = now
            if now >= self.ends_at:
                self.state = SessionState.COMPLETED
        return self.state

    def stop(self) -> None:
        if self.state == SessionState.RUNNING:
            self.state = SessionState.STOPPED
