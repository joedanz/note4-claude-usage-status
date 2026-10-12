from claude_eink.readers.usage_reader import is_login_url


def test_login_urls_are_detected():
    assert is_login_url("https://claude.ai/login?returnTo=%2Fnew")
    assert is_login_url("https://claude.ai/logout")


def test_usage_url_is_not_login():
    assert not is_login_url("https://claude.ai/new#settings/usage")
    assert not is_login_url("https://claude.ai/new")


def _args_after(cmd):
    return cmd[cmd.index("--args") + 1:]


def test_login_command_opens_plain_chrome_in_the_gui_session(tmp_path):
    from claude_eink.readers.usage_reader import chrome_login_command

    profile = tmp_path / "profile"
    cmd = chrome_login_command(profile)
    # `open` starts Chrome inside the GUI session even when launched over SSH, where the Keychain is
    # unreachable and Chrome could not save or read its encrypted cookies.
    assert cmd[:2] == ["open", "-n"] and "-W" in cmd and "-g" not in cmd     # new instance, wait, foreground
    assert cmd[cmd.index("-a") + 1] == "Google Chrome"
    args = _args_after(cmd)
    assert f"--user-data-dir={profile}" in args and args[-1] == "https://claude.ai/"
    # a normal browser window: nothing that marks it as driven by automation
    assert not any("remote-debugging" in a or "enable-automation" in a for a in args)


def test_serve_command_is_gui_session_local_only_and_offscreen(tmp_path):
    from claude_eink.readers.usage_reader import chrome_serve_command

    profile = tmp_path / "profile"
    cmd = chrome_serve_command(profile, 9333)
    assert cmd[:2] == ["open", "-n"] and "-g" in cmd and "-W" not in cmd      # background, does not wait
    assert cmd[cmd.index("-a") + 1] == "Google Chrome"
    args = _args_after(cmd)
    assert f"--user-data-dir={profile}" in args
    assert "--remote-debugging-port=9333" in args
    assert "--remote-debugging-address=127.0.0.1" in args      # never exposed beyond this Mac
    assert "--window-position=-3000,0" in args
    assert not any("enable-automation" in a for a in args)


class _Ports:
    """port_open stub that answers from a script, then keeps repeating the last answer."""

    def __init__(self, *answers):
        self.answers = list(answers)

    def __call__(self, port):
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def test_ensure_chrome_launches_it_detached_when_the_port_is_closed(tmp_path):
    from claude_eink.readers.usage_reader import chrome_serve_command, ensure_chrome

    launched = []
    ensure_chrome(
        tmp_path / "profile", 9333,
        popen=lambda cmd, **kw: launched.append((cmd, kw)),
        port_open=_Ports(False, False, True), sleep=lambda s: None,
    )
    assert len(launched) == 1
    cmd, kw = launched[0]
    assert cmd == chrome_serve_command(tmp_path / "profile", 9333)
    assert kw["start_new_session"] is True                     # survives the daemon restarting


def test_ensure_chrome_does_nothing_when_already_running(tmp_path):
    from claude_eink.readers.usage_reader import ensure_chrome

    launched = []
    ensure_chrome(tmp_path / "p", 9333, popen=lambda *a, **k: launched.append(1),
                  port_open=_Ports(True), sleep=lambda s: None)
    assert launched == []


def test_ensure_chrome_times_out_with_an_actionable_message(tmp_path):
    import pytest

    from claude_eink.models import TransientError
    from claude_eink.readers.usage_reader import ensure_chrome

    with pytest.raises(TransientError, match="Cmd\\+Q"):
        ensure_chrome(tmp_path / "p", 9333, popen=lambda *a, **k: None,
                      port_open=_Ports(False), sleep=lambda s: None, wait_s=1.0)


def test_login_refuses_while_the_collectors_chrome_is_running(tmp_path):
    from claude_eink.readers.usage_reader import login

    ran = []
    assert login(tmp_path / "p", port_open=lambda port: True, run=lambda *a, **k: ran.append(1)) is False
    assert ran == []


def test_login_opens_plain_chrome_when_nothing_is_running(tmp_path):
    from claude_eink.readers.usage_reader import chrome_login_command, login

    import subprocess

    ran = []
    assert login(tmp_path / "p", port_open=lambda port: False, run=lambda cmd, **k: ran.append((cmd, k))) is True
    cmd, kw = ran[0]
    assert cmd == chrome_login_command(tmp_path / "p")
    # Chrome's own log chatter must not flood the terminal
    assert kw["stdout"] is subprocess.DEVNULL and kw["stderr"] is subprocess.DEVNULL


SETTLED = "Your usage\nMax (20x)\nCurrent session\nResets at 5:00 PM\n4% used\nUsage credits\n$12.40"
LOADING = "Your usage\nMax (20x)\nCurrent session\nResets at 5:00 PM\n4% used\nUsage credits\nLoading\nLoading"


class FakePage:
    def __init__(self, *texts):
        self.texts = list(texts)
        self.reads = 0
        self.waited_ms = 0

    def inner_text(self, selector):
        self.reads += 1
        return self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]

    def wait_for_timeout(self, ms):
        self.waited_ms += ms


def test_is_settled_needs_percent_and_no_loading_placeholders():
    from claude_eink.readers.usage_reader import is_settled

    assert is_settled(SETTLED)
    assert not is_settled(LOADING)                       # credits still loading
    assert not is_settled("Your usage\nMax (20x)")       # nothing rendered yet


def test_read_settled_waits_for_lazy_sections_then_returns_promptly():
    from claude_eink.readers.usage_reader import _read_settled

    page = FakePage(LOADING, LOADING, SETTLED)
    assert _read_settled(page, settle_ms=12000, poll_ms=500) == SETTLED
    assert page.reads == 3


def test_read_settled_gives_up_and_returns_partial_text_instead_of_hanging():
    from claude_eink.readers.usage_reader import _read_settled

    page = FakePage(LOADING)                             # the credits call never finishes
    assert _read_settled(page, settle_ms=2000, poll_ms=500) == LOADING
    assert page.waited_ms == 2000                        # bounded wait, then return
