from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from note4_claude.models import NotLoggedIn, TransientError

USAGE_URL = "https://claude.ai/new#settings/usage"
HOME_URL = "https://claude.ai/"
CHROME_APP = "Google Chrome"
CDP_PORT = 9333
DIALOG = '[role="dialog"]'
HAS_USAGE_JS = (
    "() => { const d = document.querySelector('[role=\"dialog\"]');"
    " return !!d && d.innerText.includes('% used'); }"
)


def is_login_url(url: str) -> bool:
    path = urlparse(url).path
    return path.startswith("/login") or path.startswith("/logout")


def _open_chrome(args: list[str], *, wait: bool, background: bool) -> list[str]:
    """Start Chrome through macOS `open` so it runs inside the user's GUI session.

    A Chrome exec'd directly from an SSH session cannot reach the login Keychain, so it cannot save or
    read its encrypted cookies and every sign-in is lost. `open` asks LaunchServices to start it in the
    GUI session instead, even when the command is issued over SSH. `-n` forces a separate instance so the
    dedicated profile never attaches to the user's everyday Chrome.
    """
    cmd = ["open", "-n"]
    if background:
        cmd.append("-g")
    if wait:
        cmd.append("-W")
    return cmd + ["-a", CHROME_APP, "--args", *args]


def chrome_login_command(profile_dir: Path) -> list[str]:
    """A regular Chrome window on the dedicated profile, with no automation attached.

    Signing in here (instead of inside a Playwright-driven browser) lets Joe pass any
    "verify you are human" check normally. `-W` makes the command wait until Chrome quits.
    """
    return _open_chrome(
        [f"--user-data-dir={profile_dir}", "--no-first-run", "--no-default-browser-check", HOME_URL],
        wait=True,
        background=False,
    )


def chrome_serve_command(profile_dir: Path, port: int = CDP_PORT) -> list[str]:
    """The collector's Chrome: a normal, minimized-offscreen browser on the dedicated profile.

    Playwright only *attaches* to it over a debugging port bound to 127.0.0.1. A browser that
    Playwright launches itself is flagged as automated and loops on the human check, and it
    cannot decrypt the profile's cookies either (Playwright uses a mock Keychain).
    """
    return _open_chrome(
        [
            f"--user-data-dir={profile_dir}",
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-position=-3000,0",
            "about:blank",
        ],
        wait=False,
        background=True,
    )


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_chrome(
    profile_dir: Path,
    port: int = CDP_PORT,
    *,
    popen=subprocess.Popen,
    port_open=_port_open,
    sleep=time.sleep,
    wait_s: float = 20.0,
) -> None:
    """Make sure the collector's Chrome is up, starting it (detached) if it is not."""
    if port_open(port):
        return
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.chmod(0o700)
    popen(
        chrome_serve_command(profile_dir, port),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    waited = 0.0
    while waited < wait_s:
        if port_open(port):
            return
        sleep(0.5)
        waited += 0.5
    raise TransientError(
        "Chrome did not open its debugging port. If a Chrome is already running on the "
        "dedicated profile without it, quit that Chrome (Cmd+Q) and try again."
    )


def _devtools(port: int, path: str, method: str = "GET"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/json/{path}", method=method)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.load(resp)


def ensure_window(port: int = CDP_PORT, *, devtools=_devtools) -> None:
    """Give the collector's Chrome a tab if it has none.

    On macOS, Chrome keeps running after its last window closes but unloads the profile: the port
    still answers, yet every attach fails with "Browser context management is not supported", so
    the reads would stay stale for good. Keeping a tab of our own also means closing the reader's
    page never closes the last window.
    """
    try:
        if not any(t.get("type") == "page" for t in devtools(port, "list")):
            devtools(port, "new?about:blank", "PUT")
    except (OSError, ValueError) as e:  # refused, timed out, or not JSON
        raise TransientError(f"could not reach Chrome's DevTools: {e}") from e


def is_settled(text: str) -> bool:
    """True once the percentages are rendered and no section still shows a 'Loading' placeholder."""
    loading = any(ln.strip().lower().startswith("loading") for ln in text.splitlines())
    return "% used" in text and not loading


def _read_settled(page, *, settle_ms: int = 12000, poll_ms: int = 500) -> str:
    """Modal text once its lazily loaded sections (credits, spend) have finished.

    The percentages render first; credits and spend fill in a moment later. Wait a bounded time
    for them, then return whatever is there: those fields are optional, so a section that never
    loads must not hang or fail the read.
    """
    text = page.inner_text(DIALOG)
    waited = 0
    while not is_settled(text) and waited < settle_ms:
        page.wait_for_timeout(poll_ms)
        waited += poll_ms
        text = page.inner_text(DIALOG)
    return text


def _looks_logged_out(page) -> bool:
    if is_login_url(page.url):
        return True
    return (
        page.get_by_text("Continue with Google").count() > 0
        or page.locator('input[type="email"]').count() > 0
    )


def read_usage_text(
    profile_dir: Path,
    *,
    timeout_ms: int = 30000,
    screenshot_to: Path | None = None,
    port: int = CDP_PORT,
) -> str:
    """Open the usage modal in the collector's Chrome and return its innerText."""
    ensure_chrome(profile_dir, port)
    ensure_window(port)
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        except PWError as e:
            raise TransientError(f"could not attach to Chrome: {e}") from e
        page = None
        try:
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()
            try:
                page.goto(USAGE_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_selector(DIALOG, timeout=timeout_ms)
                page.wait_for_function(HAS_USAGE_JS, timeout=timeout_ms)
            except PWTimeout as e:
                if screenshot_to is not None:
                    page.screenshot(path=str(screenshot_to))
                if _looks_logged_out(page):
                    raise NotLoggedIn("claude.ai shows the login page") from e
                raise TransientError("usage modal did not appear in time") from e
            except PWError as e:
                raise TransientError(str(e)) from e
            if screenshot_to is not None:
                page.screenshot(path=str(screenshot_to))
            return _read_settled(page)
        finally:
            try:
                if page is not None:
                    page.close()
            except PWError:
                pass
            browser.close()  # disconnects; the Chrome itself keeps running


def login(
    profile_dir: Path,
    *,
    port: int = CDP_PORT,
    port_open=_port_open,
    run=subprocess.run,
) -> bool:
    """Open a plain Chrome on the dedicated profile so Joe can sign in once.

    Returns False without opening anything if the collector's Chrome is already running:
    a second launch on the same profile would just hand off to it.
    """
    if port_open(port):
        print(
            "The collector's Chrome is already running on the dedicated profile.\n"
            "Stop the daemon (`note4-claude uninstall`) and quit that Chrome (Cmd+Q), then run "
            "login again.",
            flush=True,
        )
        return False
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.chmod(0o700)
    print(
        "Opening Chrome on the dedicated profile. Sign in to claude.ai, then quit Chrome "
        "(Cmd+Q) to finish, so the session is saved.",
        flush=True,
    )
    run(
        chrome_login_command(profile_dir),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return True
