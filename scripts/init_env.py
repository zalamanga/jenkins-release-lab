"""Generate this lab's private values without changing system settings."""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets

from lab_config import ROOT, SECRET_KEYS, configuration, private_write


def initialize(git_ref: str | None = None) -> dict:
    values = configuration() if (ROOT / ".env").exists() else {}
    values.setdefault("LAB_JENKINS_USER", "operator")
    for key in SECRET_KEYS:
        if not values.get(key):
            values[key] = secrets.token_hex(32)
        if not re.fullmatch(r"[a-f0-9]{64}", values[key]):
            raise ValueError(f"{key} must be a private 64-character generated hexadecimal value")
    values.setdefault("LAB_JENKINS_URL", "http://127.0.0.1:8110/")
    values.setdefault("LAB_GIT_URL", "https://github.com/zalamanga/jenkins-release-lab.git")
    reference = git_ref or values.get("LAB_GIT_REF") or os.environ.get("LAB_GIT_REF", "main")
    if reference != "main" and not re.fullmatch(r"[a-f0-9]{40}", reference):
        raise ValueError("Lab Git reference must be main or an exact commit SHA")
    values["LAB_GIT_REF"] = reference
    private_write(ROOT / ".env", "\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    agent = ROOT / ".local/agent.env"
    if not agent.exists():
        private_write(agent, "JENKINS_SECRET=not-bootstrapped\n")
    private_write(ROOT / ".local/LOCAL-CREDENTIALS.txt", "Jenkins Release Lab local credentials\n\n" +
                  "Jenkins: http://127.0.0.1:8110/\nAPI gateway: http://127.0.0.1:8111\n\n" +
                  "\n".join(f"{key}={values[key]}" for key in ("LAB_JENKINS_USER", *SECRET_KEYS)) +
                  "\n\nPrivate local file. Do not commit, publish or include in screenshots.\n")
    (ROOT / ".local/tmp").mkdir(exist_ok=True)
    return {"result": "PASS", "configuration": ".env", "credentials": ".local/LOCAL-CREDENTIALS.txt", "git_ref": reference}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git-ref")
    print(json.dumps(initialize(parser.parse_args().git_ref)))
