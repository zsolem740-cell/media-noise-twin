"""Biztonságos requests.Session exponenciális backoff-fal."""
import functools

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "media-noise-twin/0.1 (+https://github.com/)"


def make_session(retries: int = 4, backoff: float = 1.5, timeout: int = 15) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    session.request = functools.partial(session.request, timeout=timeout)
    return session
