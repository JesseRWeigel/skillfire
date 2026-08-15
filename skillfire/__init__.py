"""skillfire: measure which installed Claude Code skills actually fire.

The package is deliberately split so that the one function that ever sees transcript prose
(`events.scan_file`) cannot hand that prose to anything else. It takes a matcher callable,
turns text into a token set, asks the matcher which skills the tokens hit, and drops the text.
Everything downstream of that boundary holds counts, names and timestamps only.
"""

__version__ = "1.0.0"
