"""SSRF guard for server-side fetches of user-supplied URLs.

PrintShelf fetches URLs the user hands us on the server side — model-page
imports (import_service), filament product-page imports
(filament_import_service), and the og:image / thumbnail HEAD checks that
follow. Without a guard, any logged-in user can make the server fetch an
arbitrary host: cloud metadata (169.254.169.254), localhost, or a Railway
internal address — classic SSRF.

`assert_public_url()` is the single chokepoint: call it before every outbound
fetch of a user-supplied URL. Because a public URL can still 30x-redirect to an
internal one, don't let httpx follow redirects blindly — use `safe_get` /
`safe_head` here, which re-run the guard on every hop.

Residual note: this resolves-then-checks (it does not pin the resolved IP for
the subsequent connect), so a determined DNS-rebinding attacker who flips the
record between our check and httpx's connect is not fully stopped. It blocks the
realistic cases (literal internal IPs, localhost, metadata, hosts that resolve
internal) that the import endpoints were exposed to.
"""
import ipaddress
import socket
from urllib.parse import urlparse

import httpx

ALLOWED_SCHEMES = {"http", "https"}
# No explicit port, or one of these. Everything else (SSH 22, Redis 6379,
# Postgres 5432, 8080, …) is rejected.
ALLOWED_PORTS = {80, 443}

# Belt-and-suspenders literals (all already covered by the range checks below,
# kept explicit so the intent is obvious and a future range-check change can't
# silently unblock them).
_BLOCKED_LITERALS = {"169.254.169.254", "127.0.0.1", "0.0.0.0", "::1"}


class UnsafeURLError(Exception):
    """Raised when a URL targets a disallowed / non-public destination.
    The message is safe to surface to the client."""


def _ip_is_blocked(ip) -> bool:
    return (
        str(ip) in _BLOCKED_LITERALS
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_public_url(url: str) -> str:
    """Validate that `url` is an http(s) URL pointing at a public host/port.

    Returns the URL unchanged on success; raises UnsafeURLError otherwise.

    - Scheme must be http or https (blocks javascript:, data:, file:, ftp:,
      gopher:, …).
    - Only ports 80/443 (or no explicit port) are allowed.
    - The host is resolved to *all* its A/AAAA addresses; the URL is rejected if
      ANY address falls in a private / loopback / link-local / reserved /
      multicast / unspecified range (so a hostname that resolves internal — or
      to 169.254.169.254 — is caught too, not just literal IPs).
    """
    if not url or not isinstance(url, str):
        raise UnsafeURLError("Provide a full http(s) URL")

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError("Only http(s) URLs are allowed")

    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host")
    host = host.strip().rstrip(".")  # tolerate a fully-qualified trailing dot
    if not host:
        raise UnsafeURLError("URL has no host")

    try:
        port = parsed.port
    except ValueError:
        raise UnsafeURLError("Invalid port in URL")
    if port is not None and port not in ALLOWED_PORTS:
        raise UnsafeURLError("Only ports 80 and 443 are allowed")

    try:
        infos = socket.getaddrinfo(host, port or (443 if scheme == "https" else 80))
    except socket.gaierror:
        raise UnsafeURLError("Could not resolve that host")

    if not infos:
        raise UnsafeURLError("Could not resolve that host")

    for info in infos:
        sockaddr = info[4]
        addr = sockaddr[0].split("%")[0]  # strip any IPv6 scope id
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            raise UnsafeURLError("Could not resolve that host")
        if _ip_is_blocked(ip):
            raise UnsafeURLError("That host is not allowed")

    return url


def safe_request(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    timeout: float = 15.0,
    max_redirects: int = 3,
) -> httpx.Response:
    """Fetch `url` with the SSRF guard applied to the initial URL and to every
    redirect hop. Redirects are followed manually (httpx `follow_redirects` is
    off) so a public URL can't bounce us to an internal one. Returns the final
    httpx.Response. Raises UnsafeURLError on any unsafe URL/hop."""
    assert_public_url(url)
    current = url
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        for _ in range(max_redirects + 1):
            resp = client.request(method, current, headers=headers or {})
            if resp.is_redirect:
                loc = resp.headers.get("location")
                if not loc:
                    return resp
                current = str(resp.url.join(loc))
                assert_public_url(current)
                continue
            return resp
    raise UnsafeURLError("Too many redirects")


def safe_get(url: str, *, headers: dict | None = None, timeout: float = 15.0,
             max_redirects: int = 3) -> httpx.Response:
    return safe_request("GET", url, headers=headers, timeout=timeout, max_redirects=max_redirects)


def safe_head(url: str, *, headers: dict | None = None, timeout: float = 15.0,
              max_redirects: int = 3) -> httpx.Response:
    return safe_request("HEAD", url, headers=headers, timeout=timeout, max_redirects=max_redirects)
