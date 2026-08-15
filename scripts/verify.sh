#!/usr/bin/env bash
# The verify command. Its exit code is the result.
#
# Nothing here prints success for a step it did not run. A missing dependency is a FAILURE and
# not a skip, because a skipped check and a passing check look identical in a log a week later.
#
# Nothing here reads the real transcripts either. Every step runs against the synthetic machine
# in skillfire/fixtures.py, so this passes on a laptop that has never run Claude Code, and a
# clean clone in /tmp gets the same answer as the working tree.
#
# The tree is digested before and after. A verify run that edits the repository can pass on a
# later run for reasons an earlier run created, which is indistinguishable from working.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

STEP=0
FAILED=0

step() {
  STEP=$((STEP + 1))
  printf '\n== %d. %s\n' "$STEP" "$1"
}

check() {
  if [ "$1" -eq 0 ]; then
    printf '   PASS\n'
  else
    printf '   FAIL (exit %d)\n' "$1"
    FAILED=$((FAILED + 1))
  fi
}

digest_tree() {
  "$PY" - <<'EOF'
import hashlib, os, subprocess
out = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
digest = hashlib.sha256()
for name in sorted(out.stdout.split()):
    if os.path.exists(name):
        with open(name, "rb") as handle:
            digest.update(name.encode())
            digest.update(handle.read())
print(digest.hexdigest())
EOF
}

# ---------------------------------------------------------------- interpreter

step "python"
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  printf '   FAIL no python3 on PATH. Install python 3.10 or newer; nothing below can run.\n'
  exit 1
fi
"$PY" - <<'EOF'
import sys
assert sys.version_info >= (3, 10), f"python 3.10+ required, found {sys.version.split()[0]}"
print(f"   python {sys.version.split()[0]}, standard library only")
EOF
check $?
if [ "$FAILED" -ne 0 ]; then
  printf '\nVERIFY FAILED: the interpreter is too old, so nothing below could be run honestly.\n'
  exit 1
fi
export PYTHONPATH="$ROOT"
export PYTHONDONTWRITEBYTECODE=1

BEFORE="$(digest_tree)"

# ---------------------------------------------------------------- the checks

step "unit tests"
timeout 600 "$PY" -m unittest discover -s tests -t . 2>&1 | tail -4
check "${PIPESTATUS[0]}"

step "the measurement is deterministic"
A="$(timeout 300 "$PY" scripts/measure.py | grep '^FINGERPRINT')"
B="$(timeout 300 "$PY" scripts/measure.py | grep '^FINGERPRINT')"
if [ -n "$A" ] && [ "$A" = "$B" ]; then
  printf '   %s\n' "$A"
  check 0
else
  printf '   two runs disagreed:\n     %s\n     %s\n' "$A" "$B"
  check 1
fi

step "sabotage suite, three gates and a null control"
timeout 1800 "$PY" scripts/sabotage.py 2>&1 | tail -3
check "${PIPESTATUS[0]}"

step "independent recomputation, a second reader that imports nothing from the package"
timeout 600 "$PY" scripts/check_independent.py 2>&1 | tail -10
check "${PIPESTATUS[0]}"

step "privacy scan with planted controls"
timeout 300 "$PY" scripts/privacy_scan.py
check $?

step "the published page is not stale"
timeout 300 "$PY" scripts/build_docs.py --check
check $?

step "the CLI reports the synthetic machine end to end"
OUT="$(mktemp)"
trap 'rm -f "$OUT"' EXIT
timeout 300 "$PY" - "$OUT" <<'EOF'
import json, os, subprocess, sys, tempfile
sys.path.insert(0, os.getcwd())
from skillfire import fixtures

workspace = tempfile.mkdtemp(prefix="skillfire-verify-")
home, transcripts = fixtures.materialise(workspace)
run = subprocess.run([sys.executable, "-m", "skillfire", "report", "--claude-home", home,
                      "--transcripts", transcripts],
                     capture_output=True, text=True, timeout=180,
                     env={**os.environ, "PYTHONPATH": os.getcwd()})
open(sys.argv[1], "w", encoding="utf-8").write(run.stdout + run.stderr)
if run.returncode != 0:
    print(f"   the CLI exited {run.returncode}: {run.stderr[:200]}")
    sys.exit(1)
wanted = ["never-fired-had-openings", "never-fired-no-opening", "fired",
          "trigger proxy", "user-skill-", "fired but not in the inventory"]
missing = [w for w in wanted if w not in run.stdout]
planted = fixtures.planted_values()
leaked = sorted(label for label, value in planted.items() if value in run.stdout)
raw = ""
for directory, _, names in os.walk(transcripts):
    for name in names:
        raw += open(os.path.join(directory, name), encoding="utf-8").read()
never_there = sorted(label for label, value in planted.items() if value not in raw)
print(f"   {run.stdout.splitlines()[0]}")
print(f"   {len(planted)} values planted in the transcripts, {len(leaked)} in the report")
if missing:
    print(f"   the report never mentions {missing}")
if never_there:
    print(f"   the corpus never held {never_there}, so the leak check proves nothing")
sys.exit(1 if missing or leaked or never_there else 0)
EOF
check $?

step "an empty corpus is reported as such rather than as zero fires"
timeout 120 "$PY" - <<'EOF'
import os, subprocess, sys, tempfile
empty = tempfile.mkdtemp(prefix="skillfire-empty-")
run = subprocess.run([sys.executable, "-m", "skillfire", "report", "--transcripts", empty],
                     capture_output=True, text=True, timeout=100,
                     env={**os.environ, "PYTHONPATH": os.getcwd()})
if run.returncode == 0:
    print("   scanning an empty directory exited 0, so 'no data' looks like 'no fires'")
    sys.exit(1)
print(f"   exit {run.returncode}: {run.stderr.strip().splitlines()[0][:90]}")
sys.exit(0)
EOF
check $?

step "the README carries this script's own result"
"$PY" - <<'EOF'
import re, subprocess, sys
text = open("README.md", encoding="utf-8").read()
outside = re.sub(r"```.*?```", "", text, flags=re.S)
problems = []
if "## Status" not in text:
    problems.append("no Status section")
if "## Unfinished" not in text:
    problems.append("no Unfinished section")
if "VERIFY PASSED: skillfire" not in text:
    problems.append("the Status section does not carry this script's success line")
for marker in ("TODO", "NOT YET VERIFIED", "FIXME"):
    if marker in outside:
        problems.append(f"{marker} left outside a code block")
claimed = re.search(r"Ran (\d+) tests", text)
if not claimed:
    problems.append("the transcript does not show a test count")
else:
    out = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                         capture_output=True, text=True, timeout=600)
    actual = re.search(r"Ran (\d+) tests", out.stderr)
    if not actual:
        problems.append("could not count the tests")
    elif actual.group(1) != claimed.group(1):
        problems.append(f"the README claims {claimed.group(1)} tests, there are {actual.group(1)}")
    else:
        print(f"   Status and Unfinished present, {actual.group(1)} tests as claimed")
for message in problems:
    print(f"   {message}")
sys.exit(1 if problems else 0)
EOF
check $?

# ---------------------------------------------------------------- the tree must be unchanged

step "verify did not modify the tree it was verifying"
AFTER="$(digest_tree)"
if [ "$BEFORE" = "$AFTER" ]; then
  printf '   %s tracked files unchanged\n' "$(git ls-files | wc -l)"
  check 0
else
  printf '   the tree changed during verification\n     before %s\n     after  %s\n' \
    "$BEFORE" "$AFTER"
  check 1
fi

# ---------------------------------------------------------------- result

printf '\n'
if [ "$FAILED" -eq 0 ]; then
  printf 'VERIFY PASSED: skillfire, %d of %d steps\n' "$STEP" "$STEP"
  exit 0
fi
printf 'VERIFY FAILED: %d of %d steps failed\n' "$FAILED" "$STEP"
exit 1
