from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

class Lifecycle(StrEnum):
    READY="READY"; BUILDING="BUILDING"; TESTING="TESTING"; CHECKPOINTED="CHECKPOINTED"
    REVIEWING="REVIEWING"; FIXING="FIXING"; RETESTING="RETESTING"
    GATE_EVALUATION="GATE_EVALUATION"; HUMAN_GATE="HUMAN_GATE"
    PASSED="PASSED"; MERGED="MERGED"; BLOCKED="BLOCKED"

class AgentRole(StrEnum):
    BUILDER="builder"; REVIEWER="reviewer"; FIXER="fixer"; RESEARCHER="researcher"

@dataclass(frozen=True)
class AgentRequest:
    run_id: str
    phase_id: str
    role: AgentRole
    workspace: Path
    prompt_file: Path
    output_schema_file: Path
    timeout_s: int
    allowed_write_paths: tuple[str, ...] = ()

@dataclass(frozen=True)
class AgentRunResult:
    provider: str
    exit_code: int
    timed_out: bool
    stdout: str
    stderr: str
    structured: dict[str, Any] | None
    duration_s: float

@dataclass(frozen=True)
class GateDecision:
    passed: bool
    reasons: tuple[str, ...]
    requires_human: bool = False
