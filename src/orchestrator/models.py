from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid


class StepStatus(Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    REFERENCE = "reference"


@dataclass
class Plan:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    project_root: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    parent_plan_id: Optional[str] = None


@dataclass
class PlanStep:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    plan_id: str = ""
    queue_position: int = 0
    name: str = ""
    title: str = ""
    prompt: str = ""
    description: Optional[str] = None
    result: Optional[str] = None
    status: StepStatus = StepStatus.PENDING


@dataclass
class PlanHistory:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    plan_id: str = ""
    snapshot_name: str = ""
    snapshot_at: str = field(default_factory=lambda: datetime.now().isoformat())
    summary: Optional[str] = None
    steps_json: str = "[]"


@dataclass
class AgentRun:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    step_id: str = ""
    attempt_number: int = 1
    status: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    output: Optional[str] = None
    error_message: Optional[str] = None
    exit_code: Optional[int] = None
    cost_usd: Optional[float] = None
