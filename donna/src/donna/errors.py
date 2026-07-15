"""Shared exception types."""


class CursorGone(Exception):
    """Graph returned 410 Gone for a delta link: drop the cursor and
    perform a full resync."""
