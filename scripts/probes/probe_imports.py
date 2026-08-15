"""A probe the import prover must REJECT. It imports the package outright."""

import json

from skillfire import analyze


def go(rows, corpus):
    return json.dumps(analyze.totals(rows, corpus))
