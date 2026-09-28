from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime
from typing import Iterable

from .models import Claim, ClaimFinding, Evidence, Passage, SourceChange, SourceSnapshot

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "in",
    "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "were", "with",
}

STATUS_LABELS = {
    "unchanged": "未变化",
    "changed": "已变化",
    "added": "新增要求",
    "removed": "已移除 / 无法确认",
    "no_evidence": "未找到证据",
}


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    english = re.findall(r"[a-z0-9][a-z0-9.+#-]*", lowered)
    english = [token for token in english if token not in STOPWORDS]
    chinese_groups = re.findall(r"[\u4e00-\u9fff]+", lowered)
    chinese: list[str] = []
    for group in chinese_groups:
        chinese.extend(list(group))
        chinese.extend(group[i : i + 2] for i in range(len(group) - 1))
    return english + chinese


def extract_numbers(text: str) -> set[str]:
    return set(re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", text))


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    common = set(left) & set(right)
    numerator = sum(left[token] * right[token] for token in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def rank_passages(claim: Claim, passages: list[Passage]) -> list[Evidence]:
    if not passages:
        return []

    query_tokens = tokenize(claim.text + " " + " ".join(claim.anchors))
    document_tokens = [tokenize(passage.text) for passage in passages]
    document_frequency: Counter[str] = Counter()
    for tokens in document_tokens:
        document_frequency.update(set(tokens))

    count = len(passages)
    vocabulary = set(query_tokens).union(*[set(tokens) for tokens in document_tokens])
    idf = {
        token: math.log((count + 1) / (document_frequency[token] + 1)) + 1
        for token in vocabulary
    }
    query_vector = Counter({token: value * idf[token] for token, value in Counter(query_tokens).items()})
    query_set = set(query_tokens)
    evidence: list[Evidence] = []

    for passage, tokens in zip(passages, document_tokens, strict=True):
        passage_vector = Counter({token: value * idf[token] for token, value in Counter(tokens).items()})
        cosine = _cosine(query_vector, passage_vector)
        coverage = len(query_set & set(tokens)) / max(len(query_set), 1)
        if claim.anchors:
            lowered = passage.text.lower()
            anchor_coverage = sum(anchor.lower() in lowered for anchor in claim.anchors) / len(claim.anchors)
            score = 0.55 * cosine + 0.20 * coverage + 0.25 * anchor_coverage
        else:
            score = 0.75 * cosine + 0.25 * coverage
        evidence.append(Evidence(passage.source_id, passage.passage_id, passage.text, round(score, 4)))

    return sorted(evidence, key=lambda item: (-item.score, item.source_id, item.passage_id))


def _all_passages(snapshots: dict[str, SourceSnapshot]) -> list[Passage]:
    return [passage for source in snapshots.values() for passage in source.passages]


def _best_relevant(claim: Claim, passages: list[Passage], threshold: float) -> Evidence | None:
    ranked = rank_passages(claim, passages)
    return ranked[0] if ranked and ranked[0].score >= threshold else None


def _parse_date(text: str) -> str | None:
    pattern = r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})\b"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    parsed = datetime.strptime(" ".join(match.groups()), "%B %d %Y")
    return parsed.date().isoformat()


def extract_value(claim: Claim, evidence: Evidence | None) -> str | None:
    if evidence is None:
        return None
    text = evidence.quote

    if claim.field == "min_hours":
        match = re.search(r"(\d+(?:\.\d+)?)\s*hours?\s*per\s*week", text, flags=re.IGNORECASE)
        return f"{match.group(1)} 小时/周" if match else None

    if claim.field == "deadline":
        return _parse_date(text)

    if claim.field == "salary":
        match = re.search(r"\b(HKD|USD|CNY|RMB)\s*([\d,]+)", text, flags=re.IGNORECASE)
        return f"{match.group(1).upper()} {match.group(2)}" if match else None

    if claim.field in {"location", "skill"}:
        lowered = text.lower()
        matched = [anchor for anchor in claim.anchors if anchor.lower() in lowered]
        return "、".join(matched) if matched else None

    numbers = sorted(extract_numbers(text))
    if numbers:
        return "、".join(numbers)
    return text[:100] + ("…" if len(text) > 100 else "")


def _change_summary(claim: Claim, status: str, old: str | None, new: str | None) -> str:
    if status == "unchanged":
        return f"{claim.label}未变化，当前仍为 {new or old}。"
    if status == "added":
        return f"最新岗位信息新增了{claim.label}：{new}。"
    if status == "removed":
        return f"旧版中的{claim.label}为 {old}，但新版中已找不到对应证据。"
    if status == "no_evidence":
        return f"新旧岗位信息中均未找到可证明“{claim.text}”的证据。"

    if claim.field == "deadline" and old and new:
        old_date = datetime.fromisoformat(old).date()
        new_date = datetime.fromisoformat(new).date()
        difference = (old_date - new_date).days
        if difference > 0:
            return f"{claim.label}由 {old} 提前至 {new}，提前了 {difference} 天。"
        if difference < 0:
            return f"{claim.label}由 {old} 延后至 {new}，延后了 {abs(difference)} 天。"
    return f"{claim.label}已由 {old or '未说明'} 变为 {new or '未说明'}。"


def _impact_and_action(claim: Claim, status: str) -> tuple[str, str]:
    if status == "unchanged":
        return "原有判断仍可继续使用。", "投递前打开最新岗位原文做最终确认。"
    if status == "no_evidence":
        return "该说法不能作为求职决策依据，但不代表它一定为假。", "不要写入申请材料；查看原岗位页或向招聘方确认。"
    if status == "removed":
        return "旧信息可能已经失效，继续沿用会产生误判。", "以最新岗位页为准，并人工确认该要求是否被取消。"
    if claim.field == "deadline":
        return "申请时间窗口已经改变，原计划可能导致错过截止日期。", "立即按新日期调整投递优先级和准备计划。"
    if claim.field == "min_hours":
        return "工作投入要求改变，可能影响课程、签证或时间安排判断。", "重新评估可投入时间，并更新岗位记录。"
    if claim.field == "location":
        return "工作地点变化可能影响通勤、住宿与到岗安排。", "确认是否能接受新地点或工作模式。"
    if claim.field == "skill":
        return "岗位能力要求发生变化，原匹配度判断需更新。", "调整简历重点，并确认自己是否具备新要求。"
    return "原求职判断需要重新核验。", "查看新旧证据后再决定是否继续投递。"


def align_claims(
    claims: Iterable[Claim],
    current: dict[str, SourceSnapshot],
    changes: list[SourceChange],
    previous: dict[str, SourceSnapshot] | None = None,
    threshold: float = 0.22,
) -> list[ClaimFinding]:
    current_passages = _all_passages(current)
    previous_passages = _all_passages(previous or {})
    findings: list[ClaimFinding] = []

    for claim in claims:
        current_evidence = _best_relevant(claim, current_passages, threshold)
        previous_evidence = _best_relevant(claim, previous_passages, threshold)
        current_value = extract_value(claim, current_evidence)
        previous_value = extract_value(claim, previous_evidence)

        if previous_value is None and current_value is None:
            status = "no_evidence"
        elif previous_value is None and current_value is not None:
            status = "added"
        elif previous_value is not None and current_value is None:
            status = "removed"
        elif previous_value == current_value:
            status = "unchanged"
        else:
            status = "changed"

        impact, action = _impact_and_action(claim, status)
        findings.append(
            ClaimFinding(
                claim_id=claim.claim_id,
                label=claim.label,
                claim=claim.text,
                field=claim.field,
                status=status,
                status_label=STATUS_LABELS[status],
                previous_value=previous_value,
                current_value=current_value,
                change_summary=_change_summary(claim, status, previous_value, current_value),
                impact=impact,
                recommended_action=action,
                current_evidence=current_evidence,
                previous_evidence=previous_evidence,
            )
        )
    return findings
