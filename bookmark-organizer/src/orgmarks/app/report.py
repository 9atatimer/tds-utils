"""Human-readable plan report. URLs are never truncated (auditability)."""

from __future__ import annotations

from collections import Counter

from orgmarks.domain.model import Assignment, CreateFolder, Plan


def _via_counts(moves: tuple[Assignment, ...]) -> Counter[str]:
    return Counter(move.via for move in moves)


def format_report(plan: Plan) -> str:
    """Render the plan as a plain-text summary."""
    counts = _via_counts(plan.moves)
    dropped = sum(len(group.dropped) for group in plan.dedupes)
    created = sum(1 for op in plan.folder_ops if isinstance(op, CreateFolder))

    lines = ["orgmarks plan", "-------------"]
    lines.append(f"bookmarks placed: {len(plan.moves)}")
    lines.append(
        "  by rule: {rule}, stayed: {stay}, pinned: {pin}, "
        "llm: {llm}, triaged: {triage}".format(
            rule=counts.get("rule", 0),
            stay=counts.get("stay", 0),
            pin=counts.get("pin", 0),
            llm=counts.get("llm", 0),
            triage=counts.get("triage", 0),
        )
    )
    lines.append(f"deduped: {len(plan.dedupes)} groups, {dropped} copies dropped")
    lines.append(f"folders created: {created}")
    lines.append(f"learned rules added: {len(plan.learned_rules)}")

    if plan.dedupes:
        lines.append("")
        lines.append("duplicates dropped (full URLs kept):")
        for group in plan.dedupes:
            for dropped_bm in group.dropped:
                lines.append(f"  - {dropped_bm.url} (kept {group.kept.url})")

    if plan.learned_rules:
        lines.append("")
        lines.append("learned rules:")
        for rule in plan.learned_rules:
            target = str(rule.folder)
            criterion = rule.match.domain or rule.match.url_prefix or "*"
            lines.append(f"  - {criterion} -> {target}")

    return "\n".join(lines)
