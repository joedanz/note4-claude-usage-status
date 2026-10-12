from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import httpx

from note4_claude import config as config_mod
from note4_claude import keychain, paths
from note4_claude.models import NotLoggedIn, TransientError
from note4_claude.pusher import device_id_of, list_devices
from note4_claude.readers import usage_reader
from note4_claude.state import State


def cmd_login(args) -> int:
    if not usage_reader.login(paths.profile_dir()):
        return 1
    print("Done. Run `note4-claude probe` to check the usage page can be read.")
    return 0


def _probe() -> int:
    try:
        text = usage_reader.read_usage_text(paths.profile_dir())
    except NotLoggedIn:
        print("NOT LOGGED IN: run `note4-claude login`")
        return 2
    except TransientError as e:
        print(f"TRANSIENT: {e}")
        return 3
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    start = lines.index("Your usage") if "Your usage" in lines else 0
    print("\n".join(lines[start : start + 14]))
    return 0


def cmd_preview(args) -> int:
    from note4_claude.sample import sample_pngs

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = {"usage": "page1-usage.png", "status": "page2-status.png",
             "status_degraded": "page2-status-degraded.png", "login": "login.png"}
    for key, png in sample_pngs().items():
        (out / names[key]).write_bytes(png)
    print(f"wrote {', '.join(names.values())} to {out}/")
    return 0


def cmd_setup(args) -> int:
    cfg = config_mod.load()
    if args.cloud:
        print("The macOS Keychain will ask for your ZECTRIX API key. Paste it there.")
        keychain.prompt_set_api_key()
        key = keychain.get_api_key()
        if not key:
            print("No key stored.")
            return 2
        devices = list_devices(httpx.Client(), key, cfg.api_base)
        if not devices:
            print("No devices on this account.")
            return 2
        for i, dev in enumerate(devices):
            print(f"[{i}] {dev.get('alias') or ''} {device_id_of(dev)} {dev.get('boardType') or ''}")
        idx = 0 if len(devices) == 1 else int(input("Which device? "))
        cfg.device_id = device_id_of(devices[idx])
        cfg.delivery = "cloud"
        config_mod.save(cfg)
        print(f"Saved device {cfg.device_id} to {paths.config_path()}")
        return 0
    if not cfg.device_key:
        cfg.device_key = config_mod.new_device_key()
    cfg.delivery = "lan"
    config_mod.save(cfg)
    print(f"LAN delivery is set up. The device key is in {paths.config_path()} (owner-only).")
    print("Run `note4-claude device-key` to print it, and put it in firmware/main/secrets.local.h (DEVICE_KEY).")
    return 0


def cmd_device_key(args) -> int:
    key = config_mod.load().device_key
    if not key:
        print("No device key yet: run `note4-claude setup` first.", file=sys.stderr)
        return 1
    print(key)
    return 0


def _ok(flag: bool) -> str:
    return "OK  " if flag else "FAIL"


def _gui_session() -> bool:
    import subprocess

    from note4_claude import launchd

    return subprocess.run(["launchctl", "print", launchd.gui_domain()], capture_output=True).returncode == 0


def cmd_doctor(args) -> int:
    cfg = config_mod.load()
    profile = paths.profile_dir()
    print(f"     delivery: {cfg.delivery}")
    print(f"{_ok(profile.exists())} dedicated profile at {profile}")
    print(f"{_ok(_gui_session())} GUI session (needed for the collector's Chrome)")
    if cfg.delivery == "lan":
        from note4_claude.lan_server import detect_lan_ip

        print(f"{_ok(bool(cfg.device_key))} device key in config")
        print(f"     serves on {cfg.lan_bind or detect_lan_ip()}:{cfg.lan_port}")
    else:
        key = keychain.get_api_key()
        print(f"{_ok(bool(cfg.device_id))} config device_id = {cfg.device_id or '(unset, run setup --cloud)'}")
        print(f"{_ok(bool(key))} API key in Keychain")
        if key and cfg.device_id:
            try:
                ids = [device_id_of(d) for d in list_devices(httpx.Client(), key, cfg.api_base)]
                print(f"{_ok(cfg.device_id in ids)} device reachable via Cloud API")
            except Exception as e:  # noqa: BLE001
                print(f"FAIL Cloud API: {e}")
    state = State.load(paths.state_path())
    for page, info in sorted(state.pages.items()):
        when = datetime.fromtimestamp(info["at"]).astimezone().strftime("%Y-%m-%d %H:%M")
        print(f"     page {page} last pushed {when}")
    if args.live:
        return _probe()
    return 0


def cmd_push_once(args) -> int:
    import logging

    from note4_claude import collector as collector_mod

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    collector, _ = collector_mod.build_collector(serve=False)   # the running daemon owns the LAN port
    collector.tick_status()
    collector.tick_usage()
    ok = True
    for page in collector_mod.PAGES:
        result = collector.results.get(page, "not sent")
        print(f"page {page}: {result}")
        ok = ok and result in ("pushed", "unchanged")
    return 0 if ok else 1


def cmd_run(args) -> int:
    import logging
    import threading
    from logging.handlers import RotatingFileHandler

    from note4_claude.collector import build_collector, run_forever

    paths.log_path().parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[RotatingFileHandler(paths.log_path(), maxBytes=1_000_000, backupCount=3)],
    )
    cfg = config_mod.load()
    collector, server = build_collector(cfg)
    if server is not None:
        threading.Thread(target=server.serve_forever, daemon=True, name="lan-server").start()
        logging.getLogger("note4_claude").info("serving frames on %s:%s", *server.server_address[:2])
    run_forever(collector, cfg)
    return 0


def cmd_install(args) -> int:
    from note4_claude import launchd

    print(f"Installed {launchd.install()}. Logs: {paths.log_path()}")
    return 0


def cmd_uninstall(args) -> int:
    from note4_claude import launchd

    launchd.uninstall()
    print("Removed the LaunchAgent.")
    return 0


def cmd_probe(args) -> int:
    return _probe()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="note4-claude")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="sign in once in the dedicated profile").set_defaults(fn=cmd_login)
    pr = sub.add_parser("probe", help="read the usage modal and print the top lines")
    pr.set_defaults(fn=cmd_probe)
    pv = sub.add_parser("preview", help="render sample pages to PNG (no login or device)")
    pv.add_argument("--out", default="preview")
    pv.set_defaults(fn=cmd_preview)
    su = sub.add_parser("setup", help="create the device key (LAN, default) or store the ZECTRIX API key (--cloud)")
    su.add_argument("--cloud", action="store_true", help="use ZECTRIX Cloud delivery instead of the LAN")
    su.set_defaults(fn=cmd_setup)
    sub.add_parser("device-key", help="print the device key for firmware/main/secrets.local.h").set_defaults(fn=cmd_device_key)
    dr = sub.add_parser("doctor", help="check config, key, profile, device")
    dr.add_argument("--live", action="store_true", help="also read the usage modal")
    dr.set_defaults(fn=cmd_doctor)
    sub.add_parser("push-once", help="one read and push cycle").set_defaults(fn=cmd_push_once)
    sub.add_parser("run", help="run the daemon loop").set_defaults(fn=cmd_run)
    sub.add_parser("install", help="install and start the LaunchAgent").set_defaults(fn=cmd_install)
    sub.add_parser("uninstall", help="stop and remove the LaunchAgent").set_defaults(fn=cmd_uninstall)
    return p


def main(argv: list[str] | None = None) -> int:
    from note4_claude.config import ConfigError

    args = build_parser().parse_args(argv)
    if args.fn is not cmd_preview:
        from note4_claude import migrate

        migrate.migrate_legacy()
    try:
        return args.fn(args)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
