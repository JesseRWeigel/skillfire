"""A probe the import prover must ACCEPT. It reaches the package by no route at all."""

import json
import os
import re


def count(path):
    total = 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if re.search(r'"name"\s*:\s*"Skill"', line):
                total += len(json.loads(line).get("message", {}).get("content", []))
    return total, os.path.basename(path)
