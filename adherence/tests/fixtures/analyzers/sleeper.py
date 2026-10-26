"""A fixture analyzer that never answers in time: it ignores its command
line and sleeps far past any bound a test sets, so the adapter running it
must end it (task-065)."""

import time

time.sleep(120)
