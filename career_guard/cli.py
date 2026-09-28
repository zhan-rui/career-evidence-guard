from __future__ import annotations

import argparse
import json
from pathlib import Path

from .alignment import align_claims
from .models import AnalysisResult, Claim
from .reporting import write_reports
from .snapshots import compare_snapshots, snapshot_directory
from .state_machine import RunState, StateController


SOURCE_LIMIT = 10
CLAIM_LIMIT = 25


def load_claims(path: Path) -> list[Claim]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_claims = payload.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise ValueError("Claims file must contain a non-empty 'claims' list.")

    claims: list[Claim] = []
    for raw in raw_claims:
        claim_id = str(raw.get("id", "")).strip()
        label = str(raw.get("label", raw.get("id", ""))).strip()
        text = str(raw.get("text", "")).strip()
        field = str(raw.get("field", "generic")).strip() or "generic"
        anchors = tuple(str(value).strip() for value in raw.get("anchors", []) if str(value).strip())
        if not claim_id or not label or not text:
            raise ValueError("Every claim requires non-empty 'id', 'label' and 'text' fields.")
        claims.append(Claim(claim_id=claim_id, label=label, text=text, field=field, anchors=anchors))
    return claims


def analyze(old_dir: Path, new_dir: Path, claims_path: Path, threshold: float = 0.22) -> AnalysisResult:
    controller = StateController()
    controller.transition(RunState.VALIDATING_INPUTS, "Validate the threshold, source paths and claim schema.")
    if not 0 < threshold <= 1:
        raise ValueError("Threshold must be between 0 and 1.")
    claims = load_claims(claims_path)
    if len(claims) > CLAIM_LIMIT:
        raise ValueError(f"Claim limit exceeded: {len(claims)} > {CLAIM_LIMIT}")

    controller.transition(RunState.SNAPSHOTTING_SOURCES, "Create local content-addressed source snapshots.")
    previous = snapshot_directory(old_dir)
    current = snapshot_directory(new_dir)
    if not current:
        raise ValueError("Current source directory contains no supported .md or .txt files.")
    if len(current) > SOURCE_LIMIT:
        raise ValueError(f"Source limit exceeded: {len(current)} > {SOURCE_LIMIT}")

    controller.transition(RunState.DETECTING_CHANGES, "Compare source hashes and paragraph-level content.")
    changes = compare_snapshots(previous, current)
    controller.transition(RunState.ALIGNING_EVIDENCE, "Align each claim to current and previous exact passages.")
    findings = align_claims(
        claims=claims,
        current=current,
        previous=previous,
        changes=changes,
        threshold=threshold,
    )
    controller.transition(RunState.READY_TO_REPORT, "Analysis is complete and bounded outputs are ready.")
    controller.transition(RunState.DONE, "Return the auditable analysis result.")
    return AnalysisResult(
        changes=changes,
        findings=findings,
        limits={
            "source_limit": SOURCE_LIMIT,
            "claim_limit": CLAIM_LIMIT,
            "llm_calls": 0,
            "network_calls": 0,
            "alignment_threshold": threshold,
        },
        trace=controller.trace,
    )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="career-guard",
        description="Detect job-posting changes and align application claims to exact evidence.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Compare two source snapshots and generate a decision packet.")
    scan.add_argument("--old", type=Path, required=True, help="Previous source directory")
    scan.add_argument("--new", type=Path, required=True, help="Current source directory")
    scan.add_argument("--claims", type=Path, required=True, help="Claims JSON file")
    scan.add_argument("--out", type=Path, default=Path("output"), help="Output directory")
    scan.add_argument("--threshold", type=float, default=0.22, help="Evidence-alignment threshold")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    if args.command == "scan":
        result = analyze(args.old, args.new, args.claims, args.threshold)
        markdown_path, json_path = write_reports(result, args.out)
        print(f"Decision packet: {markdown_path}")
        print(f"Machine-readable report: {json_path}")
        print(f"Claims checked: {len(result.findings)}")
        print(f"Changed / added / removed: {sum(item.status in {'changed', 'added', 'removed'} for item in result.findings)}")
        print(f"Unchanged: {sum(item.status == 'unchanged' for item in result.findings)}")
        print(f"No evidence: {sum(item.status == 'no_evidence' for item in result.findings)}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
