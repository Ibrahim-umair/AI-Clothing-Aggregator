"""
Ways out to the internet for the scraper: 'direct' (this machine's IP) or one
of the Webshare proxies in local-notes/webshare_proxies.txt.

Credentials live only in that file and in the HTTPS_PROXY of a scrape
subprocess. Everything stored or shown uses the label: 'direct' or
'proxy (<host>)'. scrub() removes user:password@ from any text before it is
logged or written to the database.

No dependency on load_data, so the API process can import this module too.
"""
import os
import re
import time
from pathlib import Path

import requests

PROXIES_FILE = Path(os.environ.get(
    "WEBSHARE_PROXIES_FILE",
    Path(__file__).resolve().parents[2] / "local-notes" / "webshare_proxies.txt"))

USER_AGENT = "Mozilla/5.0 (compatible; LibasAggregatorBot/1.0)"

# One small request per target: the store platforms the scraper depends on.
# Shopify blocks by IP across all its stores, so one store stands for all of them.
CHECK_TARGETS = {
    "shopify": "https://iznikfashions.com/products.json?limit=1",
    "sfcc": "https://pk.khaadi.com/robots.txt",
}

_CRED = re.compile(r"(//)[^/\s]*@")  # everything up to the last @ of a URL's authority


def scrub(text):
    return _CRED.sub(r"\1***@", text) if isinstance(text, str) else text


def proxies():
    """[(label, proxy_url)] in file order. proxy_url carries credentials: never log it."""
    out = []
    try:
        lines = PROXIES_FILE.read_text().split()
    except OSError:
        return out
    for line in lines:
        parts = line.split(":")
        if len(parts) < 4:
            continue
        host, port, user, pw = parts[0], parts[1], parts[2], ":".join(parts[3:])
        out.append((f"proxy ({host})", f"http://{user}:{pw}@{host}:{port}"))
    return out


def all_egress():
    """[(label, proxy_url or None)]: direct first, then the proxies."""
    return [("direct", None)] + proxies()


def check(proxy_url, target):
    """One request through proxy_url (None = direct). Returns a dict for egress_checks."""
    url = CHECK_TARGETS[target]
    session = requests.Session()
    session.trust_env = False  # a stray HTTPS_PROXY must not turn 'direct' into a proxy
    px = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    t0 = time.monotonic()
    try:
        r = session.get(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
                        proxies=px, timeout=20, stream=True)
        body = r.raw.read(decode_content=False) or b""
        nbytes = len(body) + sum(len(k) + len(v) + 4 for k, v in r.headers.items()) + 300
        return {"target": target, "http_status": r.status_code,
                "latency_ms": int((time.monotonic() - t0) * 1000), "bytes_in": nbytes, "error": None}
    except requests.RequestException as e:
        return {"target": target, "http_status": None, "latency_ms": int((time.monotonic() - t0) * 1000),
                "bytes_in": 0, "error": scrub(f"{type(e).__name__}: {e}")[:300]}
    finally:
        session.close()


def check_ok(result):
    return result.get("http_status") is not None and result["http_status"] < 400
