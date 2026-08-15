"""One materialised fixture machine, built once and shared by the whole suite."""

from __future__ import annotations

import atexit
import shutil
import tempfile

from skillfire import fixtures, pipeline

_STATE = {}


def machine():
    if "home" not in _STATE:
        workspace = tempfile.mkdtemp(prefix="skillfire-tests-")
        atexit.register(shutil.rmtree, workspace, True)
        home, transcripts = fixtures.materialise(workspace)
        _STATE["home"] = home
        _STATE["transcripts"] = transcripts
    return _STATE["home"], _STATE["transcripts"]


def analysis():
    if "analysis" not in _STATE:
        home, transcripts = machine()
        _STATE["analysis"] = pipeline.run(claude_home=home, transcripts=transcripts)
    return _STATE["analysis"]
