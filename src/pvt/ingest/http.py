"""Shared HTTP session with retries and a size cap for untrusted downloads."""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pvt import __version__

#: Generic client name (no personal or organisational contact data, see org policy).
USER_AGENT = f"prognoos-vs-tegelikkus/{__version__} (+experimental verification project)"
MAX_BYTES = 10_000_000


class FetchError(RuntimeError):
    """Raised when a download fails or is implausibly large."""


def session(retries: int = 4) -> requests.Session:
    """Return a requests session with exponential back-off on 429/5xx."""
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    retry = Retry(
        total=retries,
        backoff_factor=2.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        respect_retry_after_header=True,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def fetch_bytes(
    s: requests.Session, url: str, *, timeout_s: int = 60, max_bytes: int = MAX_BYTES
) -> bytes:
    """GET ``url`` and return the body, refusing bodies larger than ``max_bytes``."""
    try:
        with s.get(url, timeout=timeout_s, stream=True) as r:
            r.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in r.iter_content(65536):
                size += len(chunk)
                if size > max_bytes:
                    raise FetchError(f"{url}: body larger than {max_bytes} bytes")
                chunks.append(chunk)
    except requests.RequestException as exc:
        raise FetchError(f"{url}: {exc}") from exc
    return b"".join(chunks)
