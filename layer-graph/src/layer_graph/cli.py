"""layer-graph's command line, and its composition root.

    layer-graph [--root DIR] [--format json|summary] [--include-tests]
                [--no-barrels] [--out FILE]

Exit 0 with the graph; 1 when a declaration cannot be read; 2 when the
repository has no adherence.toml.
"""

import argparse
import json
import sys
from pathlib import Path

from layer_graph.adapters.disk import DiskRepository
from layer_graph.application.extract import extract
from layer_graph.domain.errors import DeclarationUnreadable, NoDeclaration
from layer_graph.domain.report import render_summary

# --- Constants ---------------------------------------------------------------

EXIT_OK = 0
EXIT_UNREADABLE = 1
EXIT_NO_DECLARATION = 2


# --- Entry point ---------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="layer-graph",
        description="Extract a repository's layer/domain graph as JSON from "
        "its adherence.toml declarations.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="repository root (default: the working directory)",
    )
    parser.add_argument(
        "--format",
        choices=("json", "summary"),
        default="json",
        help="json (default) or a short human summary",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="include the test layer's files as nodes",
    )
    parser.add_argument(
        "--no-barrels",
        action="store_true",
        help="do not see through re-export-only files (barrels)",
    )
    parser.add_argument("--out", type=Path, help="write to FILE instead of stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run layer-graph; returns the exit code."""
    args = _parser().parse_args(argv)
    try:
        graph = extract(
            source=DiskRepository(args.root),
            include_tests=args.include_tests,
            barrels=not args.no_barrels,
        )
    except NoDeclaration as error:
        print(f"layer-graph: {error}; nothing declares layers here", file=sys.stderr)
        return EXIT_NO_DECLARATION
    except DeclarationUnreadable as error:
        print(f"layer-graph: unreadable declaration: {error}", file=sys.stderr)
        return EXIT_UNREADABLE
    if args.format == "summary":
        text = render_summary(graph)
    else:
        text = json.dumps(graph.to_json(), indent=2) + "\n"
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.write_text(text, encoding="utf-8")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
