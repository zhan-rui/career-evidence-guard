from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import AnalysisResult, ClaimFinding


def _short_hash(value: str | None) -> str:
    return value[:10] if value else "—"


def _escape_table(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _display(value: str | None) -> str:
    return value if value is not None else "未找到"


def build_markdown_report(result: AnalysisResult) -> str:
    changed = [item for item in result.findings if item.status in {"changed", "added", "removed"}]
    no_evidence = [item for item in result.findings if item.status == "no_evidence"]
    unchanged = [item for item in result.findings if item.status == "unchanged"]
    overall = "请先更新求职判断再投递" if changed or no_evidence else "未发现影响投递的变化"

    lines = [
        "# Career Evidence Guard｜岗位变化检查结果",
        "",
        f"## 结论：{overall}",
        "",
        f"- **已变化 / 新增 / 移除：** {len(changed)} 项",
        f"- **未变化：** {len(unchanged)} 项",
        f"- **未找到证据：** {len(no_evidence)} 项",
        "",
    ]

    if changed:
        lines.extend(["### 需要立即处理", ""])
        for item in changed:
            lines.append(f"- **{item.change_summary}** {item.impact} **建议：{item.recommended_action}**")
        lines.append("")

    if no_evidence:
        lines.extend(["### 不能直接当作事实的信息", ""])
        for item in no_evidence:
            lines.append(f"- **{item.label}：** {item.change_summary} **建议：{item.recommended_action}**")
        lines.append("")

    lines.extend([
        "## 用户结果表",
        "",
        "| 检查项 | 结果 | 旧值 | 新值 | 对求职的影响 | 建议动作 |",
        "|---|---|---|---|---|---|",
    ])
    for item in result.findings:
        lines.append(
            f"| {_escape_table(item.label)} | **{item.status_label}** | {_escape_table(_display(item.previous_value))} | "
            f"{_escape_table(_display(item.current_value))} | {_escape_table(item.impact)} | "
            f"{_escape_table(item.recommended_action)} |"
        )

    lines.extend(["", "## 证据明细", ""])
    for item in result.findings:
        lines.extend(_finding_details(item))

    lines.extend([
        "## 来源变化记录（工程审计信息）",
        "",
        "| 来源 | 文件状态 | 旧哈希 | 新哈希 | 新增段落 | 删除段落 |",
        "|---|---|---|---|---:|---:|",
    ])
    for change in result.changes:
        lines.append(
            f"| `{change.source_id}` | `{change.status}` | `{_short_hash(change.old_sha256)}` | "
            f"`{_short_hash(change.new_sha256)}` | {len(change.added_passages)} | {len(change.removed_passages)} |"
        )

    lines.extend([
        "",
        "<details>",
        "<summary>查看执行限制与状态轨迹</summary>",
        "",
        "### 执行限制",
        "",
        *[f"- **{key}:** {value}" for key, value in result.limits.items()],
        "",
        "### 状态轨迹",
        "",
        "| From | To | Detail |",
        "|---|---|---|",
        *[
            f"| `{event['from']}` | `{event['to']}` | {_escape_table(event['detail'])} |"
            for event in result.trace
        ],
        "",
        "</details>",
        "",
        "> “未找到证据”不等于该说法为假，只表示当前提供的岗位资料不能证明它。投递前应查看最新原始岗位页面。",
        "",
    ])
    return "\n".join(lines)


def _finding_details(item: ClaimFinding) -> list[str]:
    lines = [
        f"### {item.claim_id}｜{item.label}｜{item.status_label}",
        "",
        f"- **变化说明：** {item.change_summary}",
        f"- **求职影响：** {item.impact}",
        f"- **建议动作：** {item.recommended_action}",
    ]
    if item.previous_evidence:
        lines.extend([
            f"- **旧版证据：** “{item.previous_evidence.quote}”",
            f"- **旧版证据 ID：** `{item.previous_evidence.passage_id}`",
        ])
    if item.current_evidence:
        lines.extend([
            f"- **新版证据：** “{item.current_evidence.quote}”",
            f"- **新版证据 ID：** `{item.current_evidence.passage_id}`",
        ])
    if not item.previous_evidence and not item.current_evidence:
        lines.append("- **证据：** 当前提供的资料中没有匹配原文。")
    lines.append("")
    return lines


def write_reports(result: AnalysisResult, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    markdown_path = output_dir / "decision_packet.md"
    json_path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(build_markdown_report(result), encoding="utf-8")
    return markdown_path, json_path
