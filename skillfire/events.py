"""Read Claude Code transcripts and emit facts about skills. Never prose.

The record shapes handled here were worked out by two earlier projects in this workspace,
`projects/session-search` (`sessionsearch/parse.py`) and `projects/session-fork`
(`session_fork/discover.py`), and this file reuses their conclusions rather than rediscovering
them: transcripts are JSONL under `~/.claude/projects/<flattened-cwd>/<session-id>.jsonl`; a
record has `type` in user, assistant, system, attachment; `message.content` is either a string
or a list of blocks typed text, thinking, tool_use, tool_result; `isSidechain` marks a subagent
turn; `isMeta` marks harness injection; timestamps are ISO 8601. The discovery helper is the
same shape as session-fork's. What is new here is the skill event extraction and the hard rule
below.

THE HARD RULE. `scan_file` is the only function in this package that sees transcript text, and
it does not return any. Text goes into `triggers.tokens`, the token set is intersected with a
CLOSED VOCABULARY built from public skill descriptions, and only that intersection survives. A
`SessionFacts` therefore holds an opaque session id, timestamps, integer counts, skill names
from the inventory, and per turn sets of words that were already written down in a marketplace
plugin's description before any transcript was opened. There is no field it could put a
sentence in, and `tests/test_privacy.py` asserts that against a fixture whose user turns are
full of credentials and personal detail.

Two exclusions that would otherwise wreck the measurement:

  * `<system-reminder>` blocks are stripped before tokenising. Claude Code injects the full
    listing of available skills, descriptions and all, into the first user record of a session.
    Tokenising that would make every skill's trigger vocabulary match in every session, and the
    opportunity count would become the session count exactly.
  * `isMeta` records and `tool_result` blocks are not user requests. A tool result is the
    machine talking, and including it would let a grep output decide that a skill was relevant.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import triggers

MAX_TEXT = 20000

STRIP_BLOCKS = re.compile(
    r"<(system-reminder|command-message|local-command-stdout|local-command-stderr)>"
    r".*?</\1>", re.S)
COMMAND_NAME = re.compile(r"<command-name>\s*/?([A-Za-z0-9:_-]{1,64})\s*</command-name>")
SKILL_MANIFEST = re.compile(r"(?:^|/)([A-Za-z0-9][A-Za-z0-9._-]{0,63})/SKILL\.md$")

# A skill name is model or user supplied text, so it is validated against a shape before it is
# allowed anywhere near an output file. Anything else becomes a single fixed label.
NAME_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,79}$")
UNRECOGNISED = "<unrecognised-name>"


@dataclass
class SessionFacts:
    session: str                      # sha1 of the transcript path, never the path
    first_ts: float = 0.0
    last_ts: float = 0.0
    records: int = 0
    bad_json: int = 0
    user_turns: int = 0
    sidechain_user_turns: int = 0
    truncated_turns: int = 0
    tool_calls: int = 0
    fires: list = field(default_factory=list)        # (ts, skill name, how)
    manifest_reads: list = field(default_factory=list)  # skill names read as a file
    turn_terms: list = field(default_factory=list)   # per user turn, terms from the vocabulary
    matched: dict = field(default_factory=dict)      # skill name -> user turns it matched

    @property
    def fired_names(self) -> set:
        return {name for _, name, _ in self.fires}


def safe_name(raw) -> str:
    if not isinstance(raw, str):
        return UNRECOGNISED
    raw = raw.strip()
    return raw if NAME_SHAPE.match(raw) else UNRECOGNISED


def session_id(path) -> str:
    """An opaque, stable id. The real path contains a home directory and a project name."""
    return hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:12]


def transcript_root() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECTS_DIR", Path.home() / ".claude" / "projects"))


def find(root=None, min_size: int = 1) -> list[Path]:
    root = Path(root) if root is not None else transcript_root()
    if not root.is_dir():
        return []
    out = []
    for path in root.rglob("*.jsonl"):
        try:
            if path.stat().st_size >= min_size:
                out.append(path)
        except OSError:
            continue
    return sorted(out)


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


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
        return "\n".join(parts)
    return ""


def clean_user_text(text: str) -> str:
    """Remove harness injections, then cap. Returns text that is never stored."""
    text = STRIP_BLOCKS.sub(" ", text or "")
    return text[:MAX_TEXT]


def _manifest_skill(path_value) -> str | None:
    if not isinstance(path_value, str):
        return None
    match = SKILL_MANIFEST.search(path_value.replace("\\", "/"))
    return match.group(1) if match else None


def scan_file(path, vocab, known_slash: dict | None = None) -> SessionFacts:
    """One transcript in, one SessionFacts out. No transcript text crosses this boundary."""
    known_slash = known_slash or {}
    facts = SessionFacts(session=session_id(path))

    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            facts.records += 1
            try:
                record = json.loads(line)
            except ValueError:
                facts.bad_json += 1
                continue
            if not isinstance(record, dict):
                facts.bad_json += 1
                continue

            timestamp = _iso_to_epoch(record.get("timestamp"))
            if timestamp:
                facts.first_ts = timestamp if not facts.first_ts else min(facts.first_ts,
                                                                          timestamp)
                facts.last_ts = max(facts.last_ts, timestamp)

            rtype = record.get("type")
            if rtype not in ("user", "assistant"):
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")

            if rtype == "assistant" and isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    facts.tool_calls += 1
                    name = block.get("name")
                    args = block.get("input") if isinstance(block.get("input"), dict) else {}
                    if name == "Skill":
                        facts.fires.append((timestamp, safe_name(args.get("skill")), "tool"))
                    elif name == "SlashCommand":
                        raw = args.get("command") or ""
                        head = str(raw).strip().lstrip("/").split()[0] if str(raw).strip() else ""
                        facts.fires.append((timestamp, safe_name(head), "slash"))
                    elif name in ("Read", "NotebookRead"):
                        found = _manifest_skill(args.get("file_path") or args.get("path"))
                        if found:
                            facts.manifest_reads.append(found)
                continue

            if record.get("isMeta"):
                continue
            text = _text_of(content)
            if not text:
                continue
            for raw in COMMAND_NAME.findall(text):
                if raw in known_slash:
                    facts.fires.append((timestamp, known_slash[raw], "slash"))
            text = clean_user_text(text)
            if not text.strip():
                continue
            if len(text) >= MAX_TEXT:
                facts.truncated_turns += 1
            facts.user_turns += 1
            if record.get("isSidechain"):
                facts.sidechain_user_turns += 1
            # Kept per turn, not pooled per session. Pooling a whole session's words would let
            # two unrelated requests an hour apart combine into an opportunity that never was.
            facts.turn_terms.append(vocab.present(triggers.tokens(text)))

    return facts


def resolve(facts_list, matcher) -> None:
    """Second stage: turn per turn term sets into per skill opportunity counts.

    Separate from `scan_file` because the filler filter in `triggers.prune` needs document
    frequency over the whole corpus, which is not known while the first file is being read.
    """
    for facts in facts_list:
        facts.matched = {}
        for terms in facts.turn_terms:
            for name in matcher.match(terms):
                facts.matched[name] = facts.matched.get(name, 0) + 1


def turn_frequency(facts_list) -> dict:
    """How many user turns in the corpus each vocabulary term appeared in."""
    frequency: dict[str, int] = {}
    for facts in facts_list:
        for terms in facts.turn_terms:
            for term in terms:
                frequency[term] = frequency.get(term, 0) + 1
    return frequency
