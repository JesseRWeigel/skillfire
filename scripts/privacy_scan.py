#!/usr/bin/env python3
"""Scan every tracked file for anything that should not be public, with controls that prove it read.

This project reads a machine's entire Claude Code history. Those transcripts hold credentials,
home paths, project names and whatever the person happened to type, so a scanner that quietly
reads nothing would be the last line of defence failing silently.

Five things make the scan mean something.

  * PLANTED CONTROLS THAT CARRY THEIR OWN GROUND TRUTH. The controls are written into a
    temporary directory whose path this script chooses, and they contain a home shaped path with
    an invented user name. They do not depend on the repository sitting under /home. A clean
    clone run elsewhere in this fleet found three home-path controls in another project that
    only held because the checkout happened to be there, and they would have passed on an empty
    scanner anywhere else.
  * A REFUSAL TO PASS ON A NEARLY EMPTY TREE. Before the first commit `git ls-files` returns
    nothing and a scan over zero files passes without opening one.
  * A REFUSAL TO SKIP A BINARY FILE. One NUL byte makes git and grep classify a file as binary
    and skip it, which has hidden a real token in this workspace before.
  * A CHECK THAT THE SCAN READ THE FILES THAT MATTER MOST. The package source and the README
    are named explicitly, so a `git ls-files` that returns a partial list is a failure rather
    than a quiet pass.
  * PATTERNS ASSEMBLED FROM FRAGMENTS at runtime, so this file does not match its own list, and
    credential shaped fixtures on disk are templates rather than complete shapes, so nothing has
    to be excluded from the scan to make it pass.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATTERNS = [
    ("aws access key", re.compile("AKIA" + r"[0-9A-Z]{16}")),
    ("openai style key", re.compile("sk" + "-" + r"[A-Za-z0-9]{20,}")),
    ("anthropic key", re.compile("sk" + "-ant-" + r"[A-Za-z0-9_-]{20,}")),
    ("github token", re.compile("gh" + "[pousr]" + "_" + r"[A-Za-z0-9]{30,}")),
    ("slack token", re.compile("xox" + "[abprs]" + "-" + r"[A-Za-z0-9-]{12,}")),
    ("google api key", re.compile("AIza" + r"[A-Za-z0-9_-]{30,}")),
    ("openrouter key", re.compile("sk" + "-or-v1-" + r"[A-Za-z0-9]{24,}")),
    ("private key block", re.compile("-----BEGIN " + r"[A-Z ]*PRIVATE KEY-----")),
    ("bearer header", re.compile(r"[Aa]uthorization[\"']?\s*[=:]\s*[\"']?[Bb]earer\s+"
                                 r"[A-Za-z0-9._-]{16,}")),
    ("password assignment",
     re.compile(r"(?i)\b(password|passwd|secret)\s*[=:]\s*['\"][^'\"]{6,}")),
    ("linux home path", re.compile(r"/home/[a-z][a-z0-9_-]+/")),
    ("mac home path", re.compile(r"/Users/[a-z][a-z0-9_-]+/")),
]

# This repository tracks no binaries at all, so anything binary is a finding rather than a skip.
ALLOWED_BINARY: set = set()

# Files the scan must have opened. A `git ls-files` that comes back short, from a broken repo or
# a wrong working directory, would otherwise report a clean tree it never looked at.
REQUIRED = ("README.md", "skillfire/events.py", "skillfire/fixtures.py",
            "skillfire/redact.py", "scripts/verify.sh")


def tracked_files() -> list:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                         check=False)
    return [line for line in out.stdout.splitlines() if line.strip()]


def scan_text(name: str, text: str) -> list:
    findings = []
    for label, pattern in PATTERNS:
        for match in pattern.finditer(text):
            findings.append(f"{name}: {label}: {match.group(0)[:40]}")
    return findings


def scan_file(path: str, name: str):
    extension = os.path.splitext(name)[1].lower()
    try:
        with open(path, "rb") as handle:
            blob = handle.read()
    except OSError as exc:
        return [f"{name}: could not be read: {exc.__class__.__name__}"], False
    if b"\x00" in blob:
        if extension in ALLOWED_BINARY:
            return [], False
        return [f"{name}: contains a NUL byte, so a grep based scan would skip it entirely"], \
            False
    return scan_text(name, blob.decode("utf-8", errors="replace")), True


def controls() -> int:
    """Plant, scan, and require every plant to come back. Returns 0 when the scanner is proved."""
    with tempfile.TemporaryDirectory() as tmp:
        plant = os.path.join(tmp, "planted-control.txt")
        # Every value here is invented. None of it is read from the environment, so this holds
        # identically in a clone under /tmp, under /opt, or on a machine with no /home at all.
        with open(plant, "w", encoding="utf-8") as handle:
            handle.write("aws = " + "AKIA" + "7Q2WEXAMPLE00000" + "\n")
            handle.write("gh = " + "gh" + "p" + "_" + "b" * 36 + "\n")
            handle.write("config lives at " + "/home/" + "notarealperson" + "/.claude/x\n")
            handle.write("mac config at " + "/Users/" + "notarealperson" + "/.claude/x\n")
            handle.write('password: "' + "notarealpassword" + '"\n')
        found, opened = scan_file(plant, "planted-control.txt")
        labels = {line.split(": ")[1] for line in found}
        wanted = {"aws access key", "github token", "linux home path", "mac home path",
                  "password assignment"}
        missing = sorted(wanted - labels)
        if missing or not opened:
            print(f"FAIL the planted controls were not all detected, missing {missing}. This "
                  f"scan proves nothing about the files it just read.")
            return 1

        binary = os.path.join(tmp, "planted-control.bin")
        with open(binary, "wb") as handle:
            handle.write(b"gh" + b"p" + b"_" + b"c" * 36 + b"\x00")
        found, opened = scan_file(binary, "planted-control.bin")
        if opened or not found:
            print("FAIL a file with a NUL byte was skipped silently rather than reported")
            return 1
        print(f"  controls: {len(wanted)} planted patterns detected, "
              f"a NUL byte file reported rather than skipped")
    return 0


def main() -> int:
    if controls():
        return 1

    files = tracked_files()
    if len(files) < 15:
        print(f"FAIL only {len(files)} tracked file(s). A scan over nothing passes trivially.")
        return 1
    missing = [name for name in REQUIRED if name not in files]
    if missing:
        print(f"FAIL the file list is missing {missing}, so the scan did not cover the code "
              f"that touches transcripts")
        return 1

    problems = []
    read = 0
    for name in files:
        findings, opened = scan_file(os.path.join(ROOT, name), name)
        read += 1 if opened else 0
        problems.extend(findings)

    print(f"  read {read} of {len(files)} tracked files")
    if problems:
        for message in problems:
            print(f"  FAIL {message}")
        print(f"PRIVACY SCAN FAILED with {len(problems)} finding(s)")
        return 1
    print("PRIVACY SCAN PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
