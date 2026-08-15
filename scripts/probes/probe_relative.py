"""A probe the import prover must REJECT. A relative import names no package in the source.

`from .. import triggers` mentions no module the prover could compare against a forbidden name,
so relative imports are refused outright rather than resolved.
"""

from .. import triggers


def go(text):
    return triggers.tokens(text)
