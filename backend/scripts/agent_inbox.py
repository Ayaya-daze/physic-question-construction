"""Compatibility wrapper for the physics-question-importer skill inbox tool."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_SCRIPT = Path(
    os.environ.get(
        "PHYSICS_IMPORTER_AGENT_INBOX",
        Path.home() / ".codex/skills/physics-question-importer/scripts/agent_inbox.py",
    )
)


def main() -> int:
    if not SKILL_SCRIPT.exists():
        print(f"Missing skill inbox script: {SKILL_SCRIPT}", file=sys.stderr)
        return 1
    command = [
        sys.executable,
        str(SKILL_SCRIPT),
        "--project-root",
        str(PROJECT_ROOT),
        *sys.argv[1:],
    ]
    return subprocess.call(command, cwd=PROJECT_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
