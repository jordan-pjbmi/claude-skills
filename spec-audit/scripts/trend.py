#!/usr/bin/env python3
"""Trend analysis for spec audit history.

Usage:
    python3 trend.py <audit-history-dir> [--scope SCOPE]

Analyzes all audits in the history directory and prints:
1. Findings Over Time — table + ASCII bar chart
2. Recurring Findings — grouped by fingerprint
3. Hotspot Files — specs with most findings
4. Dimension Breakdown — aggregate by dimension

No dependencies beyond the Python stdlib.
"""

import argparse
import json
import sys
from pathlib import Path


def load_history(history_dir: Path, scope_filter: str | None = None):
    """Load index and all audits/responses from history directory."""
    index_path = history_dir / "index.json"
    if not index_path.exists():
        print(f"Error: {index_path} not found", file=sys.stderr)
        sys.exit(1)

    index = json.loads(index_path.read_text())
    if scope_filter:
        index = [e for e in index if e.get("scope") == scope_filter]

    index.sort(key=lambda e: e.get("id", ""))

    audits = {}
    responses = {}
    for entry in index:
        audit_id = entry["id"]
        audit_file = history_dir / audit_id / "audit.json"
        if audit_file.exists():
            try:
                audits[audit_id] = json.loads(audit_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        resp_file = history_dir / audit_id / "responses.json"
        if resp_file.exists():
            try:
                responses[audit_id] = json.loads(resp_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass

    return index, audits, responses


def format_bar(value: int, max_value: int, width: int = 30) -> str:
    """Create an ASCII bar."""
    if max_value == 0:
        return ""
    filled = round(value / max_value * width)
    return "█" * filled + "░" * (width - filled)


def section(title: str) -> None:
    """Print a section header."""
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}\n")


def findings_over_time(index: list, audits: dict, responses: dict) -> None:
    """Section 1: Findings over time table + bar chart."""
    section("Findings Over Time")

    if not index:
        print("  No audits found.\n")
        return

    # Table header
    print(f"  {'ID':<18} {'Date':<12} {'Mode':<8} {'Tot':>4} {'Err':>4} {'Wrn':>4} {'Inf':>4}  {'Acc':>4} {'Dis':>4} {'Def':>4}  Bar")
    print(f"  {'─' * 16}  {'─' * 10}  {'─' * 6}  {'─' * 4} {'─' * 4} {'─' * 4} {'─' * 4}  {'─' * 4} {'─' * 4} {'─' * 4}  {'─' * 30}")

    max_total = max((e.get("total_findings", 0) for e in index), default=1)

    for entry in index:
        aid = entry.get("id", "?")
        date = entry.get("date", "?")
        mode = entry.get("mode", "full")
        sev = entry.get("by_severity", {})
        total = entry.get("total_findings", 0)
        err = sev.get("error", 0)
        wrn = sev.get("warning", 0)
        inf = sev.get("info", 0)

        # Response breakdown
        acc = dis = dfr = 0
        resp = responses.get(aid)
        if resp and "responses" in resp:
            for r in resp["responses"]:
                a = r.get("action")
                if a == "accept":
                    acc += 1
                elif a == "dismiss":
                    dis += 1
                elif a == "defer":
                    dfr += 1

        bar = format_bar(total, max_total, 20)
        print(f"  {aid:<18} {date:<12} {mode:<8} {total:>4} {err:>4} {wrn:>4} {inf:>4}  {acc:>4} {dis:>4} {dfr:>4}  {bar}")

    print()


def recurring_findings(index: list, audits: dict, responses: dict) -> None:
    """Section 2: Recurring findings grouped by fingerprint."""
    section("Recurring Findings")

    # Collect fingerprints across audits
    fp_data: dict[str, dict] = {}  # fingerprint -> {first, last, count, title, statuses}

    for entry in index:
        aid = entry["id"]
        audit = audits.get(aid)
        if not audit:
            continue

        resp_map = {}
        resp = responses.get(aid)
        if resp and "responses" in resp:
            for r in resp["responses"]:
                resp_map[r.get("finding_id")] = r.get("action")

        for f in audit.get("findings", []):
            fp = f.get("fingerprint")
            if not fp:
                continue

            if fp not in fp_data:
                fp_data[fp] = {
                    "first": aid,
                    "last": aid,
                    "count": 0,
                    "title": f.get("title", ""),
                    "severity": f.get("severity", "info"),
                    "statuses": [],
                }

            fp_data[fp]["last"] = aid
            fp_data[fp]["count"] += 1
            fp_data[fp]["title"] = f.get("title", fp_data[fp]["title"])
            action = resp_map.get(f.get("id"))
            if action:
                fp_data[fp]["statuses"].append(action)

    if not fp_data:
        print("  No fingerprinted findings found.")
        print("  (Legacy audits without fingerprints are skipped.)\n")
        return

    # Sort by count descending
    sorted_fps = sorted(fp_data.items(), key=lambda x: x[1]["count"], reverse=True)

    # Only show recurring (2+) or all if few
    recurring = [(fp, d) for fp, d in sorted_fps if d["count"] >= 2]
    if not recurring:
        print("  No findings appeared in more than one audit.\n")
        return

    print(f"  {'Fingerprint':<50} {'#':>3} {'First':<18} {'Last':<18} Status")
    print(f"  {'─' * 48}  {'─' * 3} {'─' * 16}  {'─' * 16}  {'─' * 12}")

    for fp, d in recurring:
        # Determine current status
        last_action = d["statuses"][-1] if d["statuses"] else "open"
        fp_display = fp[:48] if len(fp) > 48 else fp
        print(f"  {fp_display:<50} {d['count']:>3} {d['first']:<18} {d['last']:<18} {last_action}")
        # Print title on next line indented
        title = d["title"][:70] if len(d["title"]) > 70 else d["title"]
        print(f"    └ {title}")

    print()


def hotspot_files(index: list, audits: dict) -> None:
    """Section 3: Files with most findings."""
    section("Hotspot Files")

    file_counts: dict[str, int] = {}
    for entry in index:
        audit = audits.get(entry["id"])
        if not audit:
            continue
        for f in audit.get("findings", []):
            loc = f.get("location", {})
            fpath = loc.get("file", "unknown")
            file_counts[fpath] = file_counts.get(fpath, 0) + 1

    if not file_counts:
        print("  No findings to analyze.\n")
        return

    sorted_files = sorted(file_counts.items(), key=lambda x: x[1], reverse=True)
    max_count = sorted_files[0][1] if sorted_files else 1

    print(f"  {'File':<55} {'Count':>5}  Bar")
    print(f"  {'─' * 53}  {'─' * 5}  {'─' * 20}")

    for fpath, count in sorted_files[:15]:
        bar = format_bar(count, max_count, 20)
        fp_display = fpath[:53] if len(fpath) > 53 else fpath
        print(f"  {fp_display:<55} {count:>5}  {bar}")

    print()


def dimension_breakdown(index: list, audits: dict) -> None:
    """Section 4: Aggregate by dimension."""
    section("Dimension Breakdown")

    dim_counts: dict[str, int] = {}
    for entry in index:
        audit = audits.get(entry["id"])
        if not audit:
            continue
        for f in audit.get("findings", []):
            dim = f.get("dimension", "unknown")
            dim_counts[dim] = dim_counts.get(dim, 0) + 1

    if not dim_counts:
        print("  No findings to analyze.\n")
        return

    sorted_dims = sorted(dim_counts.items(), key=lambda x: x[1], reverse=True)
    max_count = sorted_dims[0][1] if sorted_dims else 1

    print(f"  {'Dimension':<25} {'Count':>5}  Bar")
    print(f"  {'─' * 23}  {'─' * 5}  {'─' * 25}")

    for dim, count in sorted_dims:
        bar = format_bar(count, max_count, 25)
        print(f"  {dim:<25} {count:>5}  {bar}")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Spec audit trend analysis")
    parser.add_argument("history_dir", type=Path, help="Path to audit-history directory")
    parser.add_argument("--scope", type=str, default=None, help="Filter to a specific scope")
    args = parser.parse_args()

    if not args.history_dir.is_dir():
        print(f"Error: {args.history_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    index, audits, responses = load_history(args.history_dir, args.scope)

    scope_label = f" (scope: {args.scope})" if args.scope else ""
    print(f"\n  Spec Audit Trend Analysis{scope_label}")
    print(f"  {len(index)} audits analyzed\n")

    findings_over_time(index, audits, responses)
    recurring_findings(index, audits, responses)
    hotspot_files(index, audits)
    dimension_breakdown(index, audits)


if __name__ == "__main__":
    main()
