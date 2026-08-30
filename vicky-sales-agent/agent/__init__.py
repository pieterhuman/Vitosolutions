"""Vicky — an autonomous outbound sales agent for Unicorn Club.

Modules are small and single-purpose; `daily_loop` orchestrates them and
`cli` is the human entry point. All state lives in SQLite (`db`), every
action is written to the audit log with a reason.
"""

__version__ = "0.1.0"
