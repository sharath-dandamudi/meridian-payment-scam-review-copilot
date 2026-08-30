"""Build a local, ignored preview from IBM AMLSim's public synthetic sample."""

from __future__ import annotations

import argparse
from pathlib import Path

from copilot.ibm_amlsim import build_preview


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("data/processed/ibm_amlsim_preview.json")
    )
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    count = build_preview(args.source, args.output, args.limit)
    print(f"Wrote {count} synthetic IBM AMLSim transactions to {args.output}")


if __name__ == "__main__":
    main()
