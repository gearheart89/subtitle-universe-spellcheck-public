"""Runtime package for Subtitle Universe Spellcheck."""

import sys

from . import subtitle_cleanup as _subtitle_cleanup

# Keep older patch/import hooks working for integrations that previously loaded
# the single-file engine from the repository root.
sys.modules.setdefault("subtitle_cleanup", _subtitle_cleanup)
