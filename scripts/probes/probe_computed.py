"""A probe the import prover must REJECT. It reaches the package through importlib.

A grep for `import skillfire` finds nothing here, which is why the prover walks the syntax
tree instead of the text.
"""

import importlib


def go():
    module = importlib.import_module("skillfire.analyze")
    return module.totals
