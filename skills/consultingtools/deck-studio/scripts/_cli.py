"""Shared --help / argument-count handling for every deck-studio script.

usage(doc, argv, min_args, max_args=None) prints the caller's module docstring and exits
with code 2 when either is true:
  - "--help" or "-h" appears anywhere in argv
  - the number of positional arguments (entries in argv not starting with "-") is outside
    the closed range [min_args, max_args]

max_args defaults to min_args (an exact positional count) when omitted. Pass an explicit
(large) max_args for a script that accepts a variable number of trailing arguments
(e.g. build_deck.py's list of slide HTML files).

A script with a value-taking flag (e.g. workroom.py's `--title NAME`) should strip that
flag's value out of the argv list it passes in here, so the value is not miscounted as a
positional argument - see workroom.py for the pattern.
"""
import sys


def usage(doc, argv, min_args, max_args=None):
    if max_args is None:
        max_args = min_args
    if "--help" in argv or "-h" in argv:
        print(doc)
        sys.exit(2)
    positional = [a for a in argv if not a.startswith("-")]
    if not (min_args <= len(positional) <= max_args):
        print(doc)
        sys.exit(2)
