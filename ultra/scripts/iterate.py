"""
Iteration loop driver (docs-first, criteria-driven).

Each pass through the loop:
  1. Runs the criteria defined in scripts/criteria.py (different criteria can be
     plugged in per phase) and prints a pass/fail table.
  2. Verifies the codebase against the blueprint (docs/ + BLUEPRINT_CHECKLIST.md),
     so the final results converge on the blueprint we keep updating.
  3. Suggests the next open item from the checklist.

Usage:
  python scripts/iterate.py                # fast pass: criteria + fast test group
  python scripts/iterate.py --full         # also run the full test suite
  python scripts/iterate.py --phase 2      # only criteria for a phase
  python scripts/iterate.py --only C3      # run a single criterion
  python scripts/iterate.py --list         # show all criteria
  python scripts/iterate.py --log "msg"    # append an iteration row to the checklist
                                           # (combine with --no-tests to skip tests)

Adding a criterion: edit scripts/criteria.py (see its docstring).
"""
import argparse
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import criteria  # noqa: E402

ROOT = criteria.ROOT
CHECKLIST = criteria.CHECKLIST


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--full", action="store_true",
                   help="also run the full test suite (C6)")
    p.add_argument("--phase", type=int, default=None,
                   help="run only criteria for this blueprint phase")
    p.add_argument("--only", default=None, help="run only this criterion id")
    p.add_argument("--list", action="store_true", help="list criteria and exit")
    p.add_argument("--log", default=None,
                   help="append an iteration row to BLUEPRINT_CHECKLIST.md")
    p.add_argument("--no-tests", action="store_true",
                   help="skip test-running criteria (C5/C6)")
    return p.parse_args()


def run_criteria(args):
    selected = criteria.CRITERIA
    if args.phase is not None:
        selected = [c for c in selected if c["phase"] == args.phase]
    if args.only:
        selected = [c for c in selected if c["id"].upper() == args.only.upper()]
    if not selected:
        print("No criteria selected.")
        return 0

    rows = []
    for c in selected:
        if c.get("full") and not args.full:
            rows.append((c, None, "skipped (use --full)"))
            continue
        if args.no_tests and c["id"] in ("C5", "C6"):
            rows.append((c, None, "skipped (--no-tests)"))
            continue
        try:
            ok, msg = c["check"]()
        except Exception as e:  # a broken check must never crash the loop
            ok, msg = False, f"check raised: {e!r}"
        rows.append((c, ok, msg))

    passed = sum(1 for _, ok, _ in rows if ok is True)
    print(f"\n=== Criteria run ({passed}/{sum(1 for r in rows if r[1] is not None)} executed) ===\n")
    for c, ok, msg in rows:
        status = "PASS" if ok is True else ("SKIP" if ok is None else "FAIL")
        print(f"[{status}] {c['id']} (phase {c['phase']}) {c['title']}\n      {msg}")
    print()
    return passed


def read_open_items():
    """Return the bullets under '## Open items for next iteration'."""
    if not os.path.isfile(CHECKLIST):
        return []
    with open(CHECKLIST, "r", encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"## Open items for next iteration\n(.*?)(\n## |\Z)", text, re.S)
    if not m:
        return []
    return [ln.strip().lstrip("-").strip() for ln in m.group(1).splitlines()
            if ln.strip().startswith("-")]


def append_iteration_row(message):
    """Append `| N | date | message | outcome |` to the iteration table."""
    with open(CHECKLIST, "r", encoding="utf-8") as fh:
        text = fh.read()
    marker = "## Open items for next iteration"
    table_end = text.find(marker)
    if table_end == -1:
        print("BLUEPRINT_CHECKLIST.md: open-items section not found")
        return 1
    header = text[:table_end]
    nums = [int(m) for m in re.findall(r"^\| (\d+) \|", header, re.M)]
    next_num = (max(nums) + 1) if nums else 1
    row = f"| {next_num} | {date.today().isoformat()} | {message} | |"
    insert_at = header.rstrip("\n")
    updated = insert_at + "\n" + row + "\n\n" + text[table_end:]
    with open(CHECKLIST, "w", encoding="utf-8") as fh:
        fh.write(updated)
    print(f"Appended iteration {next_num} to {os.path.basename(CHECKLIST)}")
    return 0


def main():
    args = parse_args()
    if args.list:
        for c in criteria.CRITERIA:
            print(f"{c['id']} (phase {c['phase']}) {c['title']}")
        return 0
    if args.log:
        code = append_iteration_row(args.log)
        if args.no_tests:
            return code
        print("(log only; pass --no-tests to skip the criteria run)")

    passed = run_criteria(args)

    open_items = read_open_items()
    print("=== Next open items (from blueprint) ===")
    if open_items:
        for i, item in enumerate(open_items[:3], 1):
            print(f"  {i}. {item}")
    else:
        print("  (none — checklist may need an 'Open items' section)")

    return 0 if passed >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
