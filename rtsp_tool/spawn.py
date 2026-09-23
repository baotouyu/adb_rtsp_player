"""Cross-platform subprocess flags to keep spawned tools from flashing a console window."""

from __future__ import annotations

import os


CREATE_NO_WINDOW = 0x08000000


def subprocess_flags() -> int:
    """Return creationflags that suppress the console on Windows; a no-op elsewhere."""
    return CREATE_NO_WINDOW if os.name == "nt" else 0