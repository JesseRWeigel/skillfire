#!/usr/bin/env python3
"""A second opinion that imports nothing from skillfire.

It drives the real CLI as a subprocess and then re-derives its headline claims by routes that
share no code with the package:

  * its own SKILL.md frontmatter reader, one regex over the whole file rather than a line by
    line state machine, and its own reading of settings.json and installed_plugins.json,
  * its own fire counter, a regex over each raw JSONL line rather than a walk of decoded
    content blocks, so a bug in the block walk cannot be reproduced here,
  * availability by LEXICAL comparison of ISO 8601 timestamp strings, never converted to epoch
    seconds, so the package's date handling is not reused to check the package's date handling,
  * a leak check against the fixture's planted credentials.

Independence is proved rather than asserted. This file's own import graph is walked with `ast`,
and the prover is shown rejecting three probes that reach the package by three different routes
and accepting one that does not.

The fixture machine is created by a subprocess, so this file never imports the generator either.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBES = os.path.join(ROOT, "scripts", "probes")
FORBIDDEN = "skillfire"
CHARS_PER_TOKEN = 4.0


# --------------------------------------------------------------------------- independence

def imported_names(path: str) -> set:
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
            if node.level:
                names.add("<relative>")
        elif isinstance(node, ast.Call):
            target = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if target in ("import_module", "__import__"):
                argument = node.args[0] if node.args else None
                names.add(argument.value.split(".")[0]
                          if isinstance(argument, ast.Constant)
                          and isinstance(argument.value, str) else "<computed>")
    return names


def prove_independence() -> list:
    problems = []
    reached = imported_names(os.path.abspath(__file__))
    for banned in (FORBIDDEN, "<computed>", "<relative>"):
        if banned in reached:
            problems.append(f"this checker reaches {banned}")
    if not problems:
        print(f"  independent: imports nothing from {FORBIDDEN}, no computed and no relative "
              f"import")
    probes = sorted(f for f in os.listdir(PROBES) if f.startswith("probe_"))
    if len(probes) < 4:
        return problems + ["too few probes on disk, so the prover was never shown able to "
                           "reject anything"]
    for name in probes:
        reached = imported_names(os.path.join(PROBES, name))
        rejects = bool({FORBIDDEN, "<computed>", "<relative>"} & reached)
        if rejects != ("clean" not in name):
            problems.append(f"{name}: the prover said {'reject' if rejects else 'accept'}")
        else:
            print(f"  {'rejected' if rejects else 'accepted'} as required: {name}")
    return problems


# --------------------------------------------------------------------------- a second reader

FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.S)
FIELD = re.compile(r"^(description|name):[ \t]*(.*(?:\n[ \t]+.*)*)$", re.M)
FIRE = re.compile(r'"name":\s*"Skill"\s*,\s*"input":\s*\{\s*"skill":\s*"([^"]*)"')
SLASH = re.compile(r"<command-name>\s*/?([A-Za-z0-9:_-]{1,64})\s*</command-name>")
ISO = re.compile(r'"timestamp":\s*"([0-9T:.\-]+Z)"')


def description_of(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    block = FRONTMATTER.match(text)
    if not block:
        return ""
    for key, value in FIELD.findall(block.group(1)):
        if key == "description":
            value = " ".join(value.split())
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value
    return ""


def read_inventory(home: str) -> dict:
    """Skill name to (description, installedAt string), plugins only plus user skills."""
    with open(os.path.join(home, "settings.json"), encoding="utf-8") as handle:
        enabled = {k for k, v in json.load(handle)["enabledPlugins"].items() if v}
    with open(os.path.join(home, "plugins", "installed_plugins.json"), encoding="utf-8") as fh:
        installed = json.load(fh)["plugins"]

    out = {}
    for plugin_id, entries in installed.items():
        if plugin_id not in enabled:
            continue
        short = plugin_id.split("@")[0]
        base = os.path.join(entries[0]["installPath"], "skills")
        since = entries[0]["installedAt"]
        if not os.path.isdir(base):
            continue
        for child in sorted(os.listdir(base)):
            manifest = os.path.join(base, child, "SKILL.md")
            if os.path.isfile(manifest):
                out[f"{short}:{child}"] = (description_of(manifest), since)
    user = os.path.join(home, "skills")
    if os.path.isdir(user):
        for child in sorted(os.listdir(user)):
            manifest = os.path.join(user, child, "SKILL.md")
            if os.path.isfile(manifest):
                out[child] = (description_of(manifest), "")
    return out


def transcripts(root: str) -> list:
    found = []
    for directory, _, names in os.walk(root):
        for name in sorted(names):
            if name.endswith(".jsonl"):
                found.append(os.path.join(directory, name))
    return sorted(found)


def count_fires(paths: list, bare_to_full: dict) -> tuple:
    """Fires by regex over raw lines, never by decoding a content block."""
    total = 0
    per_skill: dict = {}
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                names = FIRE.findall(line)
                if '"assistant"' not in line:
                    names = []
                for raw in names:
                    total += 1
                    if raw in bare_to_full:
                        per_skill[bare_to_full[raw]] = per_skill.get(bare_to_full[raw], 0) + 1
                if '"user"' in line:
                    for raw in SLASH.findall(line):
                        if raw in bare_to_full:
                            total += 1
                            full = bare_to_full[raw]
                            per_skill[full] = per_skill.get(full, 0) + 1
    return total, per_skill


def earliest_timestamp(path: str) -> str:
    """Lexical minimum of the ISO strings. Never parsed into a number."""
    best = ""
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            for stamp in ISO.findall(line):
                if not best or stamp < best:
                    best = stamp
    return best


# --------------------------------------------------------------------------- the comparison

def python(args, cwd=ROOT, env=None):
    return subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True, text=True,
                          timeout=300,
                          env={**os.environ, "PYTHONPATH": ROOT,
                               "PYTHONDONTWRITEBYTECODE": "1", **(env or {})})


def main() -> int:
    problems = prove_independence()
    workspace = tempfile.mkdtemp(prefix="skillfire-independent-")
    try:
        # The fixture machine is built by a subprocess so this file imports no generator.
        made = python(["-c", "import json,sys;from skillfire import fixtures;"
                             "h,t=fixtures.materialise(sys.argv[1]);"
                             "print(json.dumps({'home':h,'transcripts':t,"
                             "'planted':fixtures.planted_values()}))", workspace])
        if made.returncode != 0:
            print(f"  could not build the fixture machine: {made.stderr[:300]}")
            return 1
        made = json.loads(made.stdout)
        home, corpus_dir, planted = made["home"], made["transcripts"], made["planted"]

        run = python(["-m", "skillfire", "report", "--json", "--claude-home", home,
                      "--transcripts", corpus_dir])
        if run.returncode != 0:
            print(f"  the CLI failed: {run.stderr[:300]}")
            return 1
        claimed = json.loads(run.stdout)

        # ---- headline one: the inventory and what it costs in every session
        mine = read_inventory(home)
        their_names = {row["skill"] for row in claimed["skills"]}
        my_tokens = sum(int(round((len(name) + len(description)) / CHARS_PER_TOKEN))
                        for name, (description, _) in mine.items())
        if len(mine) != claimed["summary"]["skills"]:
            problems.append(f"inventory size: the CLI says {claimed['summary']['skills']}, "
                            f"a second reader finds {len(mine)}")
        if my_tokens != claimed["summary"]["standing_tokens_per_session"]:
            problems.append(
                f"standing cost: the CLI says "
                f"{claimed['summary']['standing_tokens_per_session']} tokens, a second "
                f"estimate finds {my_tokens}")
        else:
            print(f"  inventory agrees: {len(mine)} skills, {my_tokens} tokens per session")

        # ---- headline two: how many fires there were, counted by regex over raw lines
        bare = {}
        for name in mine:
            bare[name] = name
            tail = name.split(":")[-1]
            bare.setdefault(tail, name)
        paths = transcripts(corpus_dir)
        my_total, my_per_skill = count_fires(paths, bare)
        their_per_skill = {row["skill"]: row["fires"] for row in claimed["skills"]
                           if row["fires"]}
        if my_total != claimed["corpus"]["fires_total"]:
            problems.append(f"fires: the CLI says {claimed['corpus']['fires_total']}, a regex "
                            f"count finds {my_total}")
        renamed = {name: count for name, count in my_per_skill.items() if name in their_names}
        if renamed != their_per_skill:
            problems.append(f"fires per skill differ: second count {renamed}, "
                            f"CLI {their_per_skill}")
        else:
            print(f"  fires agree: {my_total} in total, {len(renamed)} skill(s) with any")

        # ---- headline three: availability, by comparing ISO strings without parsing them
        late = [name for name, (_, since) in mine.items() if since and since > "2026-03-01"]
        if not late:
            problems.append("no late installed skill in the fixture, so gating is untested")
        for name in late:
            since = mine[name][1]
            expected = 0
            for path in paths:
                first = earliest_timestamp(path)
                if not first or first >= since:
                    expected += 1
            row = next(r for r in claimed["skills"] if r["skill"] == name)
            if row["sessions_live"] != expected:
                problems.append(f"{name}: the CLI says it was live in {row['sessions_live']} "
                                f"sessions, string comparison of the timestamps says "
                                f"{expected}")
            else:
                print(f"  availability agrees: {name} live in {expected} of {len(paths)} "
                      f"sessions")

        # ---- headline four: the planted credentials
        raw = "".join(open(path, encoding="utf-8").read() for path in paths)
        absent_from_corpus = sorted(k for k, v in planted.items() if v not in raw)
        leaked = sorted(k for k, v in planted.items() if v in run.stdout)
        if absent_from_corpus:
            problems.append(f"the fixture corpus never contained {absent_from_corpus}, so the "
                            f"leak check proves nothing about them")
        if leaked:
            problems.append(f"the report leaked {leaked}")
        if not absent_from_corpus and not leaked:
            print(f"  {len(planted)} planted values are all in the corpus and none in the "
                  f"report")

        for message in problems:
            print(f"  FAIL {message}")
        if problems:
            print("INDEPENDENT CHECK FAILED")
            return 1
        print("INDEPENDENT CHECK PASSED")
        return 0
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
