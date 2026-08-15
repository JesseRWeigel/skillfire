"""A small synthetic machine: a Claude home with plugins, and a transcript corpus.

Everything measurable is measured against this, so `scripts/measure.py` gives the same answer on
any box and the sabotage suite has something stable to move.

The user turns in these transcripts are deliberately nasty. They carry API keys, a home
directory, a password, a medical detail and a person's name, because the one guarantee this
project has to make is that none of that reaches an output file. `planted_values()` returns
exactly those strings so a test can require every one of them to be absent from every rendering.

Credential shaped fixtures are TEMPLATES expanded at runtime. GitHub push protection scans full
history and rejects a push containing a complete key shape even when the key is invented, and a
later fix does not help because the shape stays in the history. `sk-{FILL:40}` on disk becomes a
complete looking key only in a temporary directory.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

PLACEHOLDER = re.compile(r"\{FILL:([a-z]+):(\d+)\}")
ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

# Fixed install instants so `available_from` is deterministic.
T0 = "2026-01-01T00:00:00.000Z"
T_LATE = "2026-06-01T00:00:00.000Z"


def expand(text: str) -> str:
    """Grow every placeholder into a deterministic string of the requested length."""
    def one(match):
        case, length = match.group(1), int(match.group(2))
        pool = UPPER if case == "upper" else ALPHABET
        return "".join(pool[(i * 7 + length) % len(pool)] for i in range(length))
    return PLACEHOLDER.sub(one, text)


PLANTED = {
    "openai key": "sk-" + "{FILL:lower:32}",
    "github token": "ghp" + "_" + "{FILL:lower:36}",
    "aws key": "AKIA" + "{FILL:upper:16}",
    "password": "hunter2-swordfish-correct",
    "home path": "/home/afakeperson/Projects/private-thing",
    "personal": "Dr Ilse Vandenberg prescribed the beta blocker",
}

# name -> (description, installed at)
PLUGIN_SKILLS = {
    "alpha:dither-images": (
        "Use when converting an image to a limited palette with Floyd-Steinberg or "
        "Riemersma dithering, or when comparing dither kernels.", T0),
    "alpha:brew-espresso": (
        "Use when dialling in an espresso grinder, adjusting extraction yield, or "
        "diagnosing channelling in a portafilter basket.", T0),
    "beta:lockfile-surgery": (
        "Use when a lockfile conflicts on merge, when pruning transitive dependencies, or "
        "when auditing a lockfile for yanked releases.", T0),
    "beta:parquet-loader": (
        "Use when reading or writing parquet, tuning row group size, or converting between "
        "parquet and arrow.", T0),
    "beta:never-relevant": (
        "Use when calibrating a spectrophotometer against a tristimulus reference tile in a "
        "metrology laboratory.", T0),
    "gamma:late-arrival": (
        "Use when scheduling a cron job, debugging a crontab timezone, or converting a "
        "schedule expression.", T_LATE),
}

USER_SKILLS = {
    "my-private-workflow": "Use when reconciling the household ledger against the bank export.",
}

DISABLED_SKILLS = {
    "delta:switched-off": "Use when rendering a mandelbrot set at arbitrary precision.",
}


def _record(kind, ts, content, **extra):
    record = {"type": kind, "timestamp": ts, "message": {"role": kind, "content": content}}
    record.update(extra)
    return record


def _tool_use(name, args, ident="t1"):
    return {"type": "tool_use", "id": ident, "name": name, "input": args}


def _sessions() -> dict:
    """Each session is a list of JSONL records. Every case the analysis has to get right."""
    key = PLANTED["openai key"]
    token = PLANTED["github token"]
    aws = PLANTED["aws key"]
    home = PLANTED["home path"]

    return {
        # A fire that also matches its own trigger vocabulary. The one case that lifts the
        # proxy's recall above zero.
        "s01-fire-in-opportunity.jsonl": [
            _record("user", "2026-03-01T10:00:00.000Z",
                    f"convert this image with Floyd-Steinberg dithering, palette of 8, "
                    f"my key is {key} and the file is under {home}"),
            _record("assistant", "2026-03-01T10:00:05.000Z",
                    [_tool_use("Skill", {"skill": "alpha:dither-images", "args": "go"})]),
        ],
        # A fire in a session whose wording never matched. This is what makes the proxy's
        # recall less than one, and the report is required to say so.
        "s02-fire-out-of-nowhere.jsonl": [
            _record("user", "2026-03-02T10:00:00.000Z", "sort it out please"),
            _record("assistant", "2026-03-02T10:00:05.000Z",
                    [_tool_use("Skill", {"skill": "beta:parquet-loader"})]),
        ],
        # Trigger vocabulary present, nothing fired at all. Displaced, unassisted.
        "s03-unassisted.jsonl": [
            _record("user", "2026-03-03T10:00:00.000Z",
                    "the lockfile conflicts on merge, prune the transitive dependencies. "
                    f"password: {PLANTED['password']}"),
            _record("assistant", "2026-03-03T10:00:05.000Z",
                    [_tool_use("Bash", {"command": "git merge"})]),
        ],
        # Trigger vocabulary present for one skill, a DIFFERENT skill fired. Displaced by skill.
        "s04-displaced.jsonl": [
            _record("user", "2026-03-04T10:00:00.000Z",
                    "the lockfile conflicts on merge and the transitive dependencies are wrong"),
            _record("assistant", "2026-03-04T10:00:05.000Z",
                    [_tool_use("Skill", {"skill": "alpha:brew-espresso"})]),
        ],
        # A skill name that is not installed, and one that is not even name shaped.
        "s05-unknown-names.jsonl": [
            _record("user", "2026-03-05T10:00:00.000Z", "do the thing"),
            _record("assistant", "2026-03-05T10:00:05.000Z",
                    [_tool_use("Skill", {"skill": "builtin-only-skill"}),
                     _tool_use("Skill", {"skill": "not a valid name!! " + token}, "t2")]),
        ],
        # A slash command that names a skill, plus a manifest read.
        "s06-slash-and-read.jsonl": [
            _record("user", "2026-03-06T10:00:00.000Z",
                    "<command-name>/parquet-loader</command-name> please"),
            _record("assistant", "2026-03-06T10:00:05.000Z",
                    [_tool_use("Read", {"file_path": "/x/skills/lockfile-surgery/SKILL.md"})]),
        ],
        # Before gamma was installed. Its trigger words are all over this one and it must not
        # count as an opportunity, because it was not there to be chosen.
        "s07-before-install.jsonl": [
            _record("user", "2026-02-01T10:00:00.000Z",
                    "the cron job crontab timezone is wrong, convert the schedule expression"),
        ],
        # After gamma was installed, same wording. This one counts.
        "s08-after-install.jsonl": [
            _record("user", "2026-07-01T10:00:00.000Z",
                    "the cron job crontab timezone is wrong, convert the schedule expression"),
        ],
        # Everything that must be ignored: a system-reminder carrying the whole skill listing,
        # a meta record, a tool_result, a sidechain turn, and a line that will not parse.
        "s09-noise.jsonl": [
            _record("user", "2026-03-09T10:00:00.000Z",
                    "<system-reminder>Available skills: alpha:dither-images, Floyd-Steinberg "
                    "dithering kernels, espresso grinder extraction yield, parquet row group "
                    "arrow, lockfile transitive dependencies yanked, spectrophotometer "
                    "tristimulus metrology, crontab timezone schedule expression"
                    "</system-reminder>"),
            _record("user", "2026-03-09T10:01:00.000Z",
                    "spectrophotometer tristimulus metrology laboratory", isMeta=True),
            {"type": "user", "timestamp": "2026-03-09T10:02:00.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t1",
                  "content": "espresso grinder portafilter channelling extraction yield"}]}},
            _record("user", "2026-03-09T10:03:00.000Z",
                    "read the parquet row group and convert it to arrow", isSidechain=True),
            {"type": "attachment", "timestamp": "2026-03-09T10:04:00.000Z"},
            _record("user", "2026-03-09T10:05:00.000Z", f"aws key {aws} for the bucket"),
        ],
        # A session with no timestamps at all.
        "s10-timeless.jsonl": [
            {"type": "user", "message": {"role": "user",
                                         "content": "dithering kernels and palette conversion"}},
        ],
    }


def materialise(workspace: str) -> tuple[str, str]:
    """Write the fake machine. Returns (claude home, transcripts directory)."""
    root = Path(workspace)
    home = root / "claude-home"
    transcripts = root / "transcripts"
    plugins = home / "plugins"
    (plugins).mkdir(parents=True, exist_ok=True)

    enabled = {}
    installed = {}
    groups: dict[str, list] = {}
    for full, (description, when) in PLUGIN_SKILLS.items():
        plugin, skill = full.split(":", 1)
        groups.setdefault(plugin, []).append((skill, description, when))
    for full, description in DISABLED_SKILLS.items():
        plugin, skill = full.split(":", 1)
        groups.setdefault(plugin, []).append((skill, description, T0))

    for plugin, entries in sorted(groups.items()):
        install_path = plugins / "cache" / plugin
        for skill, description, _ in entries:
            directory = install_path / "skills" / skill
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "SKILL.md").write_text(
                f"---\nname: {skill}\ndescription: {description}\n---\n\nBody text, "
                f"which costs nothing until the skill actually fires.\n", encoding="utf-8")
        disabled = any(f"{plugin}:{s}" in DISABLED_SKILLS for s, _, _ in entries)
        key = f"{plugin}@a-marketplace"
        enabled[key] = not disabled
        installed[key] = [{"scope": "user", "installPath": str(install_path),
                           "installedAt": entries[0][2]}]

    for skill, description in USER_SKILLS.items():
        directory = home / "skills" / skill
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: {skill}\ndescription: {description}\n---\n", encoding="utf-8")

    (home / "settings.json").write_text(
        json.dumps({"enabledPlugins": enabled}, indent=2), encoding="utf-8")
    (plugins / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": installed}, indent=2), encoding="utf-8")

    bucket = transcripts / "-home-afakeperson-Projects-private-thing"
    bucket.mkdir(parents=True, exist_ok=True)
    for name, records in sorted(_sessions().items()):
        lines = [expand(json.dumps(record)) for record in records]
        if name == "s09-noise.jsonl":
            lines.append("{not json at all")
        (bucket / name).write_text("\n".join(lines) + "\n", encoding="utf-8")

    return str(home), str(transcripts)


def planted_values() -> dict:
    return {label: expand(value) for label, value in PLANTED.items()}


def env_for(home: str, transcripts: str) -> dict:
    return {**os.environ, "SKILLFIRE_CLAUDE_HOME": home, "CLAUDE_PROJECTS_DIR": transcripts}
