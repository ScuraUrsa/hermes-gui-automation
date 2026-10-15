"""Per-OS context: active window, element under the cursor, window lookup.

``current()`` returns the module for this OS. Both modules expose the same
functions; anything a platform cannot answer returns an empty dict / None so
the recorder and drivers degrade to coordinates instead of failing.
"""

from __future__ import annotations

import fnmatch
import re
import sys
from types import ModuleType


def current() -> ModuleType:
    if sys.platform.startswith("win"):
        from hermes_teach.platform import windows
        return windows
    from hermes_teach.platform import linux
    return linux


def title_matches(pattern: str, title: str) -> bool:
    """Window title match: glob (``Invoice*``) or ``re:<regex>``; case-insensitive."""
    if pattern.startswith("re:"):
        return re.search(pattern[3:], title, re.I) is not None
    if any(c in pattern for c in "*?["):
        return fnmatch.fnmatchcase(title.lower(), pattern.lower())
    return title.lower() == pattern.lower()
