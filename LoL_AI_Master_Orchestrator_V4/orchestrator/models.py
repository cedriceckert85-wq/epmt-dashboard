from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Lifecycle(str, Enum):
    READY = "READY"
    BUILDING = "BUILDING"
    TESTING = "TESTING"
    CHECKPOINTED = "CHECKPOINTED"
    REVIEWING = "REVIEWING"
    FIXING = "FIXING"
    RETESTING = "RETESTING"
    GATE_EVALUATION = "GATE_EVALUATION"
    HUMAN_GATE = "HUMAN_GATE"
    PASSED = "PASSED"
    MERGED = "MERGED"
    BLOCKED = "BLOCKED"


class AgentRole(str, Enum):
    BUILDER = "builder"
    REVIEWER = "reviewer"
    FIXER = "fixer"
    RESEARCHER = "researcher"


@dataclass(frozen=True)
class AgentRequest:
    run_id: str
    phase_id: str
    role: AgentRole
    workspace: Path
    prompt_file: Path
    timeout_s: int
    allowed_write_paths: tuple = ()


@dataclass(frozen=True)
class AgentRunResult:
    provider: str
    exit_code: int
    timed_out: bool
    stdout: str
    stderr: str
    structured: "dict[str, Any] | None"
    duration_s: float
    cleanup_incomplete: bool = False


@dataclass(frozen=True)
class GateDecision:
    passed: bool
    reasons: tuple = ()
    requires_human: bool = False


@dataclass
class TestOutcome:
    """Outcome of one registry test execution."""
    name: str
    status: str                # "pass" | "fail" | "unverified"
    exit_code: "int | None" = None
    deferred: bool = False     # unverified due to unmet capability AND phase allows deferral
    reason: str = ""
    evidence: str = ""
    metrics: dict = field(default_factory=dict)
    duration_s: float = 0.0

    def as_exit_code(self):
        """Exit code the gate engine may trust: 0 ONLY for a real pass.

        Critically, a non-'pass' outcome must never yield 0 even when the
        underlying process exited 0 — e.g. a pytest_junit/metrics_json test
        whose process returned 0 but whose evidence was judged invalid
        (all-skipped suite, missing metrics). Returning the process's 0 there
        would let the gate treat a FAILED test as passing (fail-open)."""
        if self.status == "pass":
            return 0
        if self.exit_code not in (None, 0):
            return self.exit_code
        return 1
