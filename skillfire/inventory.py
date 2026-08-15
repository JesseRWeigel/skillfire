"""Build the list of skills that are actually loaded into a session's context.

Three populations exist on this kind of machine and only two of them cost anything:

  * skills inside an ENABLED plugin. `~/.claude/settings.json` holds `enabledPlugins`, and
    `~/.claude/plugins/installed_plugins.json` holds the install path and the install time for
    each. Only the enabled ones are described to the model, so only they spend context.
  * user skills under `~/.claude/skills` and project skills under `<project>/.claude/skills`.
  * skills inside a plugin that is installed but switched off, or a stale cached version of a
    plugin that has since been upgraded. Those sit on disk and cost nothing. Counting them
    would inflate every number in this project, and the plugin cache on this machine holds
    several versions of the same plugin, so the inflation would be large.

Cost model, stated plainly because it is the whole basis of the "earning its budget" claim.
A skill that is not invoked still puts its name and its frontmatter `description` into the
system prompt of every session. That is its standing cost. The body of `SKILL.md` is read only
when the skill fires, so the body is not counted. Tokens are estimated as characters over four,
which is an approximation and is labelled as one everywhere it is printed.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

CHARS_PER_TOKEN = 4.0

# A skill name that came off disk. Anything else is a malformed skill directory.
NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass
class Skill:
    name: str                 # "plugin:skill" for plugin skills, bare name otherwise
    source: str               # plugin id, or "user", or "project"
    origin: str               # "plugin" | "user" | "project" | "builtin"
    description: str = ""     # frontmatter description, held in memory, never emitted
    available_from: float = 0.0   # epoch seconds, 0.0 when unknown

    @property
    def desc_chars(self) -> int:
        return len(self.name) + len(self.description)

    @property
    def est_tokens(self) -> int:
        return int(round(self.desc_chars / CHARS_PER_TOKEN))


@dataclass
class InventoryStats:
    enabled_plugins: int = 0
    plugins_without_path: int = 0
    skill_dirs_seen: int = 0
    malformed: int = 0
    no_description: int = 0
    disabled_on_disk: int = 0
    notes: list = field(default_factory=list)


def _iso_to_epoch(value) -> float:
    if not value:
        return 0.0
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 1000.0 if v > 1e11 else v
    try:
        import datetime
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def parse_frontmatter(text: str) -> dict:
    """Read the leading YAML block of a SKILL.md.

    Only three shapes occur in the skills on this machine: `key: value`, a value continued on
    following indented lines, and a value in single or double quotes. A real YAML parser is not
    a dependency worth taking for that, and `name` and `description` are all this needs.
    """
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end]
    fields: dict[str, str] = {}
    key = None
    for raw in block.splitlines():
        if not raw.strip():
            continue
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s?(.*)$", raw)
        if match and not raw.startswith((" ", "\t")):
            key = match.group(1).strip()
            fields[key] = match.group(2).strip()
        elif key is not None and raw.startswith((" ", "\t")):
            fields[key] = (fields[key] + " " + raw.strip()).strip()
    for key, value in list(fields.items()):
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            fields[key] = value[1:-1]
    return fields


def _read_skill_dir(directory: Path, prefix: str, source: str, origin: str,
                    since: float, stats: InventoryStats) -> list[Skill]:
    out: list[Skill] = []
    if not directory.is_dir():
        return out
    for child in sorted(directory.iterdir()):
        manifest = child / "SKILL.md"
        if not manifest.is_file():
            continue
        stats.skill_dirs_seen += 1
        if not NAME_OK.match(child.name):
            stats.malformed += 1
            continue
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            stats.malformed += 1
            continue
        fields = parse_frontmatter(text)
        description = fields.get("description", "")
        if not description:
            stats.no_description += 1
        name = f"{prefix}:{child.name}" if prefix else child.name
        out.append(Skill(name=name, source=source, origin=origin,
                         description=description, available_from=since))
    return out


def claude_home() -> Path:
    return Path(os.environ.get("SKILLFIRE_CLAUDE_HOME", Path.home() / ".claude"))


def load_settings(home: Path) -> dict:
    path = home / "settings.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_installed(home: Path) -> dict:
    path = home / "plugins" / "installed_plugins.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("plugins", {}) if isinstance(data, dict) else {}


def build(home: Path | None = None, project_dirs=()) -> tuple[list[Skill], InventoryStats]:
    home = home or claude_home()
    stats = InventoryStats()
    settings = load_settings(home)
    enabled = {k for k, v in (settings.get("enabledPlugins") or {}).items() if v}
    installed = load_installed(home)

    skills: list[Skill] = []
    for plugin_id in sorted(installed):
        entries = installed[plugin_id]
        if not isinstance(entries, list) or not entries:
            continue
        entry = entries[0]
        install_path = entry.get("installPath") or ""
        short = plugin_id.split("@")[0]
        if plugin_id not in enabled:
            # Present on disk and switched off. It spends no context, so it is counted and
            # then dropped rather than silently ignored.
            stats.disabled_on_disk += 1
            continue
        stats.enabled_plugins += 1
        if not install_path or not Path(install_path).is_dir():
            stats.plugins_without_path += 1
            continue
        since = _iso_to_epoch(entry.get("installedAt"))
        root = Path(install_path)
        found = _read_skill_dir(root / "skills", short, plugin_id, "plugin", since, stats)
        # Some plugins ship their skills one level deeper, under a directory named for the
        # plugin, and some vendor a second copy under `.claude/skills`. Both shapes exist in
        # the cache on this machine.
        for extra in (root / ".claude" / "skills", root / short / "skills"):
            found += _read_skill_dir(extra, short, plugin_id, "plugin", since, stats)
        seen: set[str] = set()
        for skill in found:
            if skill.name in seen:
                continue
            seen.add(skill.name)
            skills.append(skill)

    skills += _read_skill_dir(home / "skills", "", "user", "user", 0.0, stats)
    for project in project_dirs:
        skills += _read_skill_dir(Path(project) / ".claude" / "skills", "", "project",
                                  "project", 0.0, stats)

    by_name: dict[str, Skill] = {}
    for skill in skills:
        by_name.setdefault(skill.name, skill)
    return sorted(by_name.values(), key=lambda s: s.name), stats


def standing_cost(skills) -> dict:
    """What the whole installed set costs in every single session, before anything fires."""
    chars = sum(s.desc_chars for s in skills)
    return {
        "skills": len(skills),
        "description_chars": chars,
        "est_tokens": int(round(chars / CHARS_PER_TOKEN)),
        "chars_per_token_assumed": CHARS_PER_TOKEN,
    }
