#!/usr/bin/env python3
import json
from pathlib import Path
import re
import subprocess
import sys


def fetch(root):
    lock = json.loads((root / "upstream.lock.json").read_text(encoding="utf-8"))
    commit = lock["commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("upstream.lock.json must pin a full commit")
    target = root / ".local" / "upstream"
    target.mkdir(parents=True, exist_ok=True)

    def git(*args):
        result = subprocess.run(["git", "-C", str(target), *args], text=True,
                                capture_output=True, timeout=180)
        if result.returncode:
            raise RuntimeError("Pinned upstream fetch failed")
        return result.stdout.strip()

    if not (target / ".git").exists():
        if any(target.iterdir()):
            raise RuntimeError("Refusing to replace a non-Git upstream directory")
        git("init")
        git("remote", "add", "origin", lock["repository"])
    if git("remote", "get-url", "origin") != lock["repository"]:
        raise RuntimeError("Upstream origin does not match its lock")
    if git("status", "--porcelain"):
        raise RuntimeError("Upstream checkout contains local modifications")
    git("fetch", "--depth", "1", "origin", commit)
    git("checkout", "--detach", commit)
    if git("rev-parse", "HEAD") != commit:
        raise RuntimeError("Fetched upstream revision does not match its lock")
    print("Fetched immutable ReserveFlow upstream " + commit)


if __name__ == "__main__":
    try:
        fetch(Path(__file__).resolve().parents[1])
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(str(error) if isinstance(error, RuntimeError) else "Pinned upstream fetch failed", file=sys.stderr)
        raise SystemExit(1)
