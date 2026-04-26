#!/usr/bin/env python3
"""Backward-compatible wrapper for the packaged monitor."""

from hubitat_stuff.monitor import run


if __name__ == "__main__":
    raise SystemExit(run())
