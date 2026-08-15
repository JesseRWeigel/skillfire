#!/usr/bin/env python3
"""Break skillfire on purpose and require the suite to notice.

A green suite proves nothing on its own. It has to be shown failing on a tree that is really
wrong, or "all green" only means "nothing ran".

Three gates, and a sabotage scores only if it clears all three.

  1. It APPLIES. The edit changed the file. A patch whose target text has drifted does nothing,
     and a suite that passes against an unmodified tree looks like a suite that caught something.
  2. It MOVES THE MEASUREMENT. `scripts/measure.py` prints a different fingerprint.
  3. Only then, it is CAUGHT. The unit suite fails.

Dormant code inverts gate 2. `redact.scrub` has nothing to redact while the structural rule in
events.py holds, so disabling it cannot change the output. For those the requirement is the
opposite and stricter: fingerprint UNCHANGED and the suite fails anyway. A guard whose removal
moves the output was never dormant and is rerun as a plain attack.

The null control runs first. An unmodified copy of the tree, in a directory with a different
name and a different path length, must fingerprint identically. If it does not, the measurement
tracks the working directory, gate 2 is free for every sabotage below, and the run proves
nothing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = {".git", ".venv", "__pycache__", "docs"}
RUN_TIMEOUT = 300

# (name, file, find, replace, dormant)
SABOTAGES = [
    # ---------------------------------------------------------------- inventory
    ("a plugin that is switched off is counted as loaded context",
     "skillfire/inventory.py",
     "        if plugin_id not in enabled:",
     "        if False:", False),
    ("frontmatter is never parsed, so every skill looks free",
     "skillfire/inventory.py",
     '    if not text.startswith("---"):\n        return {}',
     "    return {}", False),
    ("skills the user wrote are not part of the inventory",
     "skillfire/inventory.py",
     '    skills += _read_skill_dir(home / "skills", "", "user", "user", 0.0, stats)',
     "    pass", False),
    ("install time is discarded, so every skill looks like it was always there",
     "skillfire/inventory.py",
     '        since = _iso_to_epoch(entry.get("installedAt"))',
     "        since = 0.0", False),
    ("the SKILL.md body is charged to the standing cost",
     "skillfire/inventory.py",
     "        return len(self.name) + len(self.description)",
     "        return len(self.name) + len(self.description) * 3", False),

    # ---------------------------------------------------------------- transcript scanning
    ("the injected skill listing is left in, so every skill matches everywhere",
     "skillfire/events.py",
     '    text = STRIP_BLOCKS.sub(" ", text or "")',
     "    text = text or ''", False),
    ("harness injected meta records are read as if the human typed them",
     "skillfire/events.py",
     '            if record.get("isMeta"):\n                continue',
     "            if False:\n                continue", False),
    ("tool output is read as if it were a request",
     "skillfire/events.py",
     '            if isinstance(block, dict) and block.get("type") == "text":\n'
     '                parts.append(block.get("text") or "")',
     '            if isinstance(block, dict):\n'
     '                parts.append(block.get("text") or block.get("content") or "")', False),
    ("a skill name from a transcript is printed without being validated",
     "skillfire/events.py",
     "    return raw if NAME_SHAPE.match(raw) else UNRECOGNISED",
     "    return raw", False),
    ("a slash command that names a skill is not a fire",
     "skillfire/events.py",
     "            for raw in COMMAND_NAME.findall(text):",
     "            for raw in []:", False),
    ("opening a SKILL.md as a plain file is not recorded",
     "skillfire/events.py",
     "                        if found:",
     "                        if False:", False),
    ("the session identifier is the transcript path",
     "skillfire/events.py",
     '    return hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:12]',
     "    return str(path)", False),
    ("terms are kept whether or not they came from the closed vocabulary",
     "skillfire/events.py",
     "            facts.turn_terms.append(vocab.present(triggers.tokens(text)))",
     "            facts.turn_terms.append(frozenset(triggers.tokens(text)))", False),

    # ---------------------------------------------------------------- trigger vocabulary
    ("one shared word is enough to call a situation an opportunity",
     "skillfire/triggers.py",
     "MIN_DISTINCT_HITS = 2",
     "MIN_DISTINCT_HITS = 1", False),
    ("a word every skill uses is kept as a trigger term",
     "skillfire/triggers.py",
     "        keep = [t for t in terms if spread[t] <= MAX_SKILLS_PER_TERM]",
     "        keep = list(terms)", False),
    ("the small corpus floor is removed, so document frequency eats the vocabulary",
     "skillfire/triggers.py",
     "    ceiling = max(max_ratio * total_turns, MIN_TURN_CEILING) if total_turns else 0",
     "    ceiling = max_ratio * total_turns if total_turns else 0", False),
    ("two word phrases are not trigger terms",
     "skillfire/triggers.py",
     '        if previous:\n            out.add(previous + " " + word)',
     "        if previous:\n            pass", False),
    ("the corpus frequency filter never drops anything",
     "skillfire/triggers.py",
     "    dropped = sorted(term for term in vocab.terms "
     "if turn_frequency.get(term, 0) > ceiling)",
     "    dropped = []", False),

    # ---------------------------------------------------------------- analysis
    ("capture rate counts fires from sessions that were never opportunities",
     "skillfire/analyze.py",
     "        return self.fires_in_opportunity / self.opportunities",
     "        return self.fire_sessions / self.opportunities", False),
    ("a skill counts as available in sessions that predate its install",
     "skillfire/analyze.py",
     "            live = (not row.available_from) or (not facts.first_ts) or \\\n"
     "                facts.first_ts >= row.available_from",
     "            live = True", False),
    ("displacement by another skill is filed as unassisted",
     "skillfire/analyze.py",
     "                row.displaced_by_skill += 1",
     "                row.displaced_unassisted += 1", False),
    ("a rare situation is reported as dead weight",
     "skillfire/analyze.py",
     '        if self.opportunities:\n            return "never-fired-had-openings"\n'
     '        return "never-fired-no-opening"',
     '        return "never-fired-had-openings"', False),
    ("a fire naming an uninstalled skill is credited to the inventory",
     "skillfire/analyze.py",
     "                corpus.fires_unknown_skill += 1",
     "                corpus.fires_total += 0", False),
    ("standing spend ignores how many sessions carried the skill",
     "skillfire/analyze.py",
     "        return self.est_tokens * self.sessions_live",
     "        return self.est_tokens", False),

    # ---------------------------------------------------------------- reporting
    ("a skill the user wrote is named in the report",
     "skillfire/redact.py",
     '    if origin in ("plugin", "builtin"):\n        return name',
     "    return name", False),

    # ---------------------------------------------------------------- the scrubber
    # These were written as dormant guards and the harness said otherwise, which is the whole
    # point of running gate 2 on a guard. One fixture session fires a skill whose name is
    # shaped like a credential, and a skill name is legal input, so the scrubber has real work
    # to do on every run and disabling it is observable. They are scored as plain attacks.
    ("the output scrubber is a no-op", "skillfire/redact.py",
     "    if not text:\n        return text",
     "    return text", False),
    ("the home path rule is anchored on the running user's own home",
     "skillfire/redact.py",
     'HOME_SHAPED = re.compile(r"/(home|Users)/[A-Za-z][A-Za-z0-9_.-]*")',
     "HOME_SHAPED = re.compile(re.escape(os.path.expanduser('~')))", True),
    ("the credential patterns are emptied", "skillfire/redact.py",
     "SECRET_PATTERNS = [",
     "SECRET_PATTERNS = []\n_UNUSED_PATTERNS = [", False),
    ("the text report is not scrubbed on the way out", "skillfire/report.py",
     '    return redact.scrub("\\n".join(lines))',
     '    return "\\n".join(lines)', False),
    ("the JSON report is not scrubbed on the way out", "skillfire/report.py",
     "    return redact.scrub(json.dumps(payload, indent=2, sort_keys=True))",
     "    return json.dumps(payload, indent=2, sort_keys=True)", False),
]


def copy_tree(destination: str) -> None:
    os.makedirs(destination, exist_ok=True)
    for name in os.listdir(ROOT):
        if name in SKIP:
            continue
        source = os.path.join(ROOT, name)
        target = os.path.join(destination, name)
        if os.path.isdir(source):
            shutil.copytree(source, target, ignore=shutil.ignore_patterns(*SKIP))
        else:
            shutil.copy2(source, target)


def run(tree: str, args: list[str]):
    try:
        return subprocess.run(
            [sys.executable, *args], cwd=tree, capture_output=True, text=True,
            timeout=RUN_TIMEOUT,
            env={**os.environ, "PYTHONPATH": tree, "PYTHONDONTWRITEBYTECODE": "1"})
    except subprocess.TimeoutExpired:
        return None


def fingerprint(tree: str):
    out = run(tree, ["scripts/measure.py"])
    if out is None:
        return None
    for line in out.stdout.splitlines():
        if line.startswith("FINGERPRINT "):
            return line.split(" ", 1)[1].strip()
    return None


def tests_pass(tree: str) -> bool:
    out = run(tree, ["-m", "unittest", "discover", "-s", "tests", "-t", ".", "-f"])
    return out is not None and out.returncode == 0


def main() -> int:
    workspace = tempfile.mkdtemp(prefix="skillfire-sabotage-")
    try:
        baseline_tree = os.path.join(workspace, "baseline")
        copy_tree(baseline_tree)
        baseline = fingerprint(baseline_tree)
        if baseline is None:
            print("FAIL the baseline tree produced no fingerprint at all")
            return 1

        control_tree = os.path.join(workspace, "a-differently-named-copy-of-the-same-tree")
        copy_tree(control_tree)
        control = fingerprint(control_tree)
        if control != baseline:
            print("FAIL null control: an unmodified copy fingerprinted differently.")
            print(f"     baseline {baseline}\n     control  {control}")
            print("     The measurement tracks the working directory, so gate 2 would be free")
            print("     for every sabotage below. Not scoring this run.")
            return 1
        print(f"null control: an unmodified copy fingerprints identically ({baseline[:16]})")

        if not tests_pass(baseline_tree):
            print("FAIL the suite does not pass on an unsabotaged tree, so a failure below "
                  "would mean nothing")
            return 1
        print("baseline: the suite passes before anything is broken\n")

        caught = 0
        failures: list[str] = []
        for index, (name, relative, find, replace, dormant) in enumerate(SABOTAGES):
            tree = os.path.join(workspace, f"s{index:02d}")
            copy_tree(tree)
            path = os.path.join(tree, relative)
            with open(path, encoding="utf-8") as handle:
                original = handle.read()
            if find not in original:
                failures.append(f"{name}: DID NOT APPLY, the target text is not in {relative}")
                print(f"  gate 1 FAIL  {name}")
                continue
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(original.replace(find, replace, 1))

            moved = fingerprint(tree)
            if dormant:
                if moved is None:
                    failures.append(f"{name}: the tree stopped producing a fingerprint at all, "
                                    f"so it is broken rather than dormant")
                    print(f"  gate 2 FAIL  {name} (no output)")
                    continue
                if moved != baseline:
                    failures.append(
                        f"{name}: expected dormant code, but the measurement moved. It was "
                        f"doing something visible, so rerun it as a plain attack instead.")
                    print(f"  gate 2 FAIL  {name} (dormant code changed the output)")
                    continue
            else:
                if moved is None:
                    failures.append(f"{name}: the tree stopped producing a fingerprint at all")
                    print(f"  gate 2 FAIL  {name} (no output to compare)")
                    continue
                if moved == baseline:
                    failures.append(
                        f"{name}: APPLIED but changed nothing measurable. Either the fixture "
                        f"never exercises this path or the fingerprint cannot see it.")
                    print(f"  gate 2 FAIL  {name} (output unchanged)")
                    continue

            if tests_pass(tree):
                failures.append(f"{name}: NOT CAUGHT, the suite passed on a broken tree")
                print(f"  gate 3 FAIL  {name}")
                continue

            caught += 1
            print(f"  caught       {name} ({'dormant' if dormant else 'output moved'})")

        print()
        total = len(SABOTAGES)
        dormant_count = sum(1 for s in SABOTAGES if s[4])
        print(f"{caught} of {total} sabotages caught "
              f"({dormant_count} of them scored under the dormant rule)")
        for message in failures:
            print(f"  FAIL {message}")
        if failures:
            print("SABOTAGE SUITE FAILED")
            return 1
        print("SABOTAGE SUITE PASSED")
        return 0
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
