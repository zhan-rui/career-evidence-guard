from __future__ import annotations

import hashlib
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from .models import Passage, SourceChange, SourceSnapshot

SUPPORTED_SUFFIXES = {".md", ".txt"}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def clean_markdown_line(line: str) -> str:
    line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
    line = re.sub(r"^\s*[-*+]\s+", "", line)
    line = re.sub(r"^\s*>\s?", "", line)
    return line.strip()


def split_passages(text: str) -> list[str]:
    """Split Markdown/TXT into stable, readable paragraph-sized passages."""
    normalized = normalize_text(text)
    blocks = re.split(r"\n\s*\n", normalized)
    passages: list[str] = []
    for block in blocks:
        lines = [clean_markdown_line(line) for line in block.splitlines()]
        cleaned = " ".join(line for line in lines if line)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            passages.append(cleaned)
    return passages


def snapshot_directory(directory: Path) -> dict[str, SourceSnapshot]:
    directory = directory.resolve()
    if not directory.exists() or not directory.is_dir():
        raise ValueError(f"Source directory does not exist: {directory}")

    snapshots: dict[str, SourceSnapshot] = {}
    for path in sorted(p for p in directory.rglob("*") if p.suffix.lower() in SUPPORTED_SUFFIXES):
        relative = path.relative_to(directory).as_posix()
        raw = path.read_text(encoding="utf-8")
        normalized = normalize_text(raw)
        passage_texts = split_passages(normalized)
        occurrences: Counter[str] = Counter()
        passage_items: list[Passage] = []
        for index, passage in enumerate(passage_texts, start=1):
            passage_hash = sha256_text(passage)
            occurrences[passage_hash] += 1
            passage_items.append(
                Passage(
                    source_id=relative,
                    passage_id=f"{relative}::h{passage_hash[:12]}-{occurrences[passage_hash]:02d}",
                    index=index,
                    text=passage,
                    sha256=passage_hash,
                )
            )
        passages = tuple(passage_items)
        snapshots[relative] = SourceSnapshot(
            source_id=relative,
            path=str(path),
            sha256=sha256_text(normalized),
            passages=passages,
        )
    return snapshots


def compare_snapshots(
    old: dict[str, SourceSnapshot], new: dict[str, SourceSnapshot]
) -> list[SourceChange]:
    changes: list[SourceChange] = []
    for source_id in sorted(set(old) | set(new)):
        before = old.get(source_id)
        after = new.get(source_id)

        if before is None and after is not None:
            changes.append(
                SourceChange(
                    source_id=source_id,
                    status="added",
                    old_sha256=None,
                    new_sha256=after.sha256,
                    added_passages=tuple(p.text for p in after.passages),
                    changed_current_passage_ids=tuple(p.passage_id for p in after.passages),
                )
            )
            continue

        if before is not None and after is None:
            changes.append(
                SourceChange(
                    source_id=source_id,
                    status="removed",
                    old_sha256=before.sha256,
                    new_sha256=None,
                    removed_passages=tuple(p.text for p in before.passages),
                )
            )
            continue

        assert before is not None and after is not None
        if before.sha256 == after.sha256:
            changes.append(
                SourceChange(
                    source_id=source_id,
                    status="unchanged",
                    old_sha256=before.sha256,
                    new_sha256=after.sha256,
                )
            )
            continue

        old_text = [p.text for p in before.passages]
        new_text = [p.text for p in after.passages]
        matcher = SequenceMatcher(a=old_text, b=new_text, autojunk=False)
        added: list[str] = []
        removed: list[str] = []
        changed_ids: list[str] = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in {"delete", "replace"}:
                removed.extend(old_text[i1:i2])
            if tag in {"insert", "replace"}:
                added.extend(new_text[j1:j2])
                changed_ids.extend(p.passage_id for p in after.passages[j1:j2])

        changes.append(
            SourceChange(
                source_id=source_id,
                status="modified",
                old_sha256=before.sha256,
                new_sha256=after.sha256,
                added_passages=tuple(added),
                removed_passages=tuple(removed),
                changed_current_passage_ids=tuple(changed_ids),
            )
        )
    return changes
