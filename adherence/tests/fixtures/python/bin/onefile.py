#!/usr/bin/env python3
"""A one-file tool."""
import json

COUNTER = 0


# --- Predicates ---
def is_even(n: int) -> bool:
    return n % 2 == 0


# --- Action functions ---
def load(path: str) -> dict:
    global COUNTER
    COUNTER += 1
    return json.load(open(path))
