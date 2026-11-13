"""Code-version provenance stamped on every archived row (docs/06 section 3)."""

from __future__ import annotations

import functools
import logging
import os
import subprocess

from pvt import __version__
from pvt.config import REPO_ROOT

LOG = logging.getLogger(__name__)


@functools.cache
def ingest_version() -> str:
    """Return the code version: ``$PVT_INGEST_VERSION``, else the git hash, else package version.

    A ``-dirty`` suffix marks uncommitted changes, so rows written by modified code are
    distinguishable from rows written by a commit.
    """
    env = os.environ.get("PVT_INGEST_VERSION")
    if env:
        return env
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        LOG.warning("git not available; using package version as ingest_version")
        return f"pvt-{__version__}"
    return f"{head}-dirty" if dirty else head
