"""Command line entrypoint.

    python -m report_engine bundle.json -o report.html

Reads a bundle, writes a report. No database, no control plane, and with
`--no-judge` (the default today) no network at all — which is also what makes
this the regression harness.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from report_engine.render import to_html, to_json
from report_engine.schema import SessionBundle
from report_engine.score import build_report


def main(argv: list[str] | None = None) -> int:
    """Run the engine over one bundle file."""
    parser = argparse.ArgumentParser(prog="report_engine", description=__doc__)
    parser.add_argument("bundle", type=Path, help="path to a session bundle JSON")
    parser.add_argument("-o", "--out", type=Path, help="write HTML here")
    parser.add_argument("--json", type=Path, help="write the report JSON here")
    parser.add_argument(
        "--english-weight",
        type=float,
        default=None,
        help="weight English into the index (omit for advisory only)",
    )
    parser.add_argument(
        "--no-language-gate",
        action="store_true",
        help="score a non-English session anyway, with a stamped warning",
    )
    args = parser.parse_args(argv)

    bundle = SessionBundle.model_validate_json(args.bundle.read_text(encoding="utf-8"))
    if args.english_weight is not None:
        bundle.scoring_options.english_weight = args.english_weight
    if args.no_language_gate:
        bundle.scoring_options.language_gate = False

    report = build_report(bundle)

    if args.out:
        args.out.write_text(to_html(report), encoding="utf-8")
    if args.json:
        args.json.write_text(to_json(report), encoding="utf-8")
    if not args.out and not args.json:
        sys.stdout.write(to_json(report))

    if report.unscoreable:
        print(f"not scored: {report.unscoreable}", file=sys.stderr)
        return 2
    print(
        f"readiness {report.readiness_index} ({report.band}) · "
        f"{len(report.question_acts)} question acts · out: {args.out or args.json or 'stdout'}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
