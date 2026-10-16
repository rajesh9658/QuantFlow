#!/usr/bin/env python3
"""CI check: zero hardcoded values in dashboard/src outside config/."""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "dashboard" / "src"

if not SRC_DIR.is_dir():
    print(f"Error: Dashboard src directory not found at {SRC_DIR}")
    sys.exit(1)

print(f"Running Zero Hardcoded Values check on {SRC_DIR}...")
failed = False

URL_PATTERN = re.compile(r"(https?|wss?)://")
HOST_PATTERN = re.compile(r"(localhost|127\.0\.0\.1)")
API_PATTERN = re.compile(r"/api/v1")
ENV_PATTERN = re.compile(r"(process\.env|import\.meta\.env)")

for file_path in SRC_DIR.rglob("*"):
    if not file_path.is_file() or file_path.suffix not in (".ts", ".tsx", ".js", ".jsx"):
        continue

    rel_path = file_path.relative_to(SRC_DIR).as_posix()

    # Skip config, test, types, and vite-env.d.ts
    parts = rel_path.split("/")
    if "config" in parts or "test" in parts or "types" in parts:
        continue
    if file_path.name == "vite-env.d.ts":
        continue

    content = file_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    for idx, line in enumerate(lines, start=1):
        # 1. URL check
        if URL_PATTERN.search(line):
            print(f"FAILED: Hardcoded URL in {rel_path}:{idx}\n  {line.strip()}")
            failed = True

        # 2. Host check
        if HOST_PATTERN.search(line):
            print(f"FAILED: Hardcoded host/IP in {rel_path}:{idx}\n  {line.strip()}")
            failed = True

        # 3. API route check
        if API_PATTERN.search(line):
            print(f"FAILED: Literal /api/v1 in {rel_path}:{idx}\n  {line.strip()}")
            failed = True

        # 4. Env access check
        if ENV_PATTERN.search(line):
            print(f"FAILED: Direct env access in {rel_path}:{idx}\n  {line.strip()}")
            failed = True

if failed:
    print("\nZero Hardcoded Values check FAILED.")
    sys.exit(1)

print("\nZero Hardcoded Values check PASSED.")
sys.exit(0)
