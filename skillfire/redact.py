"""Two layers between a private machine and anything this tool prints.

Layer one is structural and does the real work: `events.SessionFacts` has no field that can hold
a sentence, so transcript prose has nowhere to go. Layer two is this file, which assumes layer
one will be broken one day by someone adding a convenient debug field.

  * `public_name` decides which skill names may be printed. A plugin skill's name is public
    marketplace text. A skill the user wrote under `~/.claude/skills`, or one living inside a
    project, is named by the user and the name alone can say what the user is working on, so it
    becomes a stable hash instead.
  * `scrub` is a last pass over rendered output. It collapses the home directory, rewrites any
    other home shaped path, and masks credential shaped strings. Patterns are built from
    fragments so this file does not match its own list.

`scrub` returning its input unchanged is the normal case and is the point. It is dormant while
layer one holds, which is exactly why the sabotage suite scores it under the dormant rule:
disabling it must not move the fingerprint, and the unit suite must fail anyway.
"""

from __future__ import annotations

import hashlib
import os
import re

SECRET_PATTERNS = [
    re.compile("AKIA" + r"[0-9A-Z]{16}"),
    re.compile("sk" + "-ant-" + r"[A-Za-z0-9_-]{20,}"),
    re.compile("sk" + "-" + r"[A-Za-z0-9]{20,}"),
    re.compile("gh" + "[pousr]" + "_" + r"[A-Za-z0-9]{30,}"),
    re.compile("xox" + "[abprs]" + "-" + r"[A-Za-z0-9-]{12,}"),
    re.compile("AIza" + r"[A-Za-z0-9_-]{30,}"),
    re.compile("-----BEGIN " + r"[A-Z ]*PRIVATE KEY-----"),
]

# Deliberately not anchored on the running user's home. A control that only fires because the
# repository happens to sit under /home passes on this machine and fails everywhere else.
HOME_SHAPED = re.compile(r"/(home|Users)/[A-Za-z][A-Za-z0-9_.-]*")

MASK = "[redacted]"


def public_name(name: str, origin: str) -> str:
    if origin in ("plugin", "builtin"):
        return name
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"{origin}-skill-{digest}"


def scrub(text: str) -> str:
    if not text:
        return text
    home = os.path.expanduser("~")
    if home and home not in ("/", ""):
        text = text.replace(home, "~")
    text = HOME_SHAPED.sub("/home/[user]", text)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(MASK, text)
    return text
