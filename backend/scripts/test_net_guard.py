"""Unit tests for net_guard.assert_public_url — the SSRF guard on server-side
fetches of user-supplied import URLs. No server/DB/network required (internal
targets are literal IPs or names that resolve locally; the allow cases use
public IP literals so getaddrinfo short-circuits without a DNS lookup).

Run: python backend/scripts/test_net_guard.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from net_guard import UnsafeURLError, assert_public_url  # noqa: E402

passed = 0
failed = 0


def expect_block(label: str, url: str):
    global passed, failed
    try:
        assert_public_url(url)
    except UnsafeURLError:
        passed += 1
        print(f"  ok   BLOCK  {label}")
        return
    except Exception as e:  # noqa: BLE001
        failed += 1
        print(f"  FAIL BLOCK  {label}: raised {type(e).__name__} not UnsafeURLError")
        return
    failed += 1
    print(f"  FAIL BLOCK  {label}: was allowed, expected block")


def expect_allow(label: str, url: str):
    global passed, failed
    try:
        assert_public_url(url)
    except Exception as e:  # noqa: BLE001
        failed += 1
        print(f"  FAIL ALLOW  {label}: blocked with {type(e).__name__}: {e}")
        return
    passed += 1
    print(f"  ok   ALLOW  {label}")


# --- SSRF targets that MUST be rejected --------------------------------------
expect_block("cloud metadata 169.254.169.254", "http://169.254.169.254/latest/meta-data/")
expect_block("cloud metadata over https", "https://169.254.169.254/")
expect_block("localhost name", "http://localhost/admin")
expect_block("loopback literal 127.0.0.1", "http://127.0.0.1:8000/")
expect_block("loopback 127.x other octet", "http://127.1.2.3/")
expect_block("ipv6 loopback ::1", "http://[::1]/")
expect_block("private 10.x", "http://10.0.0.5/")
expect_block("private 192.168.x", "http://192.168.1.1/")
expect_block("private 172.16.x", "http://172.16.0.1/")
expect_block("link-local 169.254.x", "http://169.254.10.20/")
expect_block("unspecified 0.0.0.0", "http://0.0.0.0/")
expect_block("ipv6 unique-local fd00", "http://[fd00::1]/")

# --- Non-http(s) schemes MUST be rejected ------------------------------------
expect_block("javascript: scheme", "javascript:alert(1)")
expect_block("data: scheme", "data:text/html,<script>1</script>")
expect_block("file: scheme", "file:///etc/passwd")
expect_block("ftp: scheme", "ftp://example.com/x")
expect_block("gopher: scheme", "gopher://127.0.0.1:6379/_x")

# --- Non-standard ports MUST be rejected -------------------------------------
expect_block("public IP on SSH port 22", "http://1.1.1.1:22/")
expect_block("public IP on 8080", "http://8.8.8.8:8080/")
expect_block("public IP on redis 6379", "http://1.1.1.1:6379/")

# --- Malformed / empty MUST be rejected --------------------------------------
expect_block("empty string", "")
expect_block("no host", "http://")

# --- Legitimate public destinations MUST be allowed --------------------------
expect_allow("public IP 1.1.1.1 (no port)", "http://1.1.1.1/")
expect_allow("public IP 8.8.8.8 https", "https://8.8.8.8/some/path")
expect_allow("public IP explicit :443", "https://1.1.1.1:443/x")
expect_allow("public IP explicit :80", "http://8.8.8.8:80/x")

print(f"\n{'=' * 40}\n  {passed}/{passed + failed} passed\n{'=' * 40}")
sys.exit(1 if failed else 0)
