from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ChangeStatus = Literal["unchanged", "added", "removed", "modified"]
ResultStatus = Literal["unchanged", "changed", "added", "removed", "no_evidence"]


@dataclass(frozen=True)
class Passage:
    source_id: str
    passage_id: str
    index: int
    text: str
    sha256: str


@dataclass(frozen=True)
class SourceSnapshot:
    source_id: str
    path: str
    sha256: str
    passages: tuple[Passage, ...]


@dataclass(frozen=True)
class SourceChange:
    source_id: str
    status: ChangeStatus
    old_sha256: str | None
    new_sha256: str | None
    added_passages: tuple[str, ...] = ()
    removed_passages: tuple[str, ...] = ()
    changed_current_passage_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Claim:
    claim_id: str
    label: str
    text: str
    field: str = "generic"
    anchors: tuple[str, ...] = ()


@dataclass(frozen=True)
class Evidence:
    source_id: str
    passage_id: str
    quote: str
    score: float


@dataclass(frozen=True)
class ClaimFinding:
    claim_id: str
    label: str
    claim: str
    field: str
    status: ResultStatus
    status_label: str
    previous_value: str | None
    current_value: str | None
    change_summary: str
    impact: str
    recommended_action: str
    current_evidence: Evidence | None
    previous_evidence: Evidence | None


@dataclass
class AnalysisResult:
    changes: list[SourceChange] = field(default_factory=list)
    findings: list[ClaimFinding] = field(default_factory=list)
    limits: dict[str, int | float] = field(default_factory=dict)
    trace: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
