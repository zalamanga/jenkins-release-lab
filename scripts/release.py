#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from release_lab.core import LabError
from release_lab.engine import Engine


def main():
    parser = argparse.ArgumentParser(description="Run an isolated Jenkins release step")
    parser.add_argument("command", choices=("test", "package", "deploy", "post", "status", "audit-reports"))
    args = parser.parse_args()
    try:
        getattr(Engine(), args.command.replace("-", "_"))()
        return 0
    except LabError as error:
        print("Release lab: " + str(error), file=sys.stderr)
        return 1
    except Exception:
        # Third-party CLI/HTTP exceptions may embed private input in their messages.
        print("Release lab: unexpected operation failure; inspect sanitized reports", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
