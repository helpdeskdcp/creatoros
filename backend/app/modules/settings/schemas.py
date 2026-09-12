from datetime import datetime

from pydantic import BaseModel


class KillSwitchOut(BaseModel):
    is_active: bool
    activated_at: datetime | None
    reason: str | None


class ActivateKillSwitchRequest(BaseModel):
    reason: str | None = None


class ControlCenterOut(BaseModel):
    """The Autonomous Control Center dashboard payload."""

    kill_switch: KillSwitchOut
    connected_channels: int
    active_publishing_rules: int
    pending_runs: int
    completed_runs: int
    failed_runs: int
