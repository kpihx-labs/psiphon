"""Conservative native TUN routing, with only session-scoped owned resources."""

import json
import os
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

from psiphon import config
from psiphon.supervisor import run


def active_route() -> dict[str, Any]:
    routes = json.loads(run(["ip", "-j", "-4", "route", "get", config.ROUTE_PROBE_IP]))
    if not routes or "dev" not in routes[0]:
        raise RuntimeError("No usable IPv4 route")
    return routes[0]


def table_routes(family: str) -> list[dict]:
    # Query by numeric ID directly: an rt_tables alias must not hide occupancy.
    result = subprocess.run(
        ["ip", "-j", family, "route", "show", "table", config.ROUTE_TABLE],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode:
        if "FIB table does not exist" in result.stderr:
            return []
        raise RuntimeError(f"Cannot inspect reserved table: {result.stderr.strip()}")
    return json.loads(result.stdout)


def preflight(interface: str | None = None) -> str:
    for tool in ("ip", "resolvectl", "sysctl"):
        if not shutil.which(tool):
            raise RuntimeError(f"Required tool missing: {tool}")
    if not Path("/dev/net/tun").exists():
        raise RuntimeError("/dev/net/tun is missing")
    if Path("/etc/resolv.conf").resolve() != Path(
        "/run/systemd/resolve/stub-resolv.conf"
    ):
        raise RuntimeError(
            "Native DNS requires the systemd-resolved stub; refusing to rewrite resolv.conf"
        )
    # Specific global domains remain intact. Their resolver traffic follows the
    # TUN policy too; private names may be unavailable during the session.
    uplink = interface or str(active_route()["dev"])
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,15}", uplink) or uplink in (
        "lo",
        config.TUN_NAME,
    ):
        raise ValueError("Invalid bypass interface")
    links = json.loads(run(["ip", "-j", "link", "show"]))
    names = {link["ifname"] for link in links}
    if uplink not in names or config.TUN_NAME in names:
        raise RuntimeError("Bypass interface missing or reserved TUN already exists")
    for family in ("-4", "-6"):
        rules = json.loads(run(["ip", "-j", family, "rule", "show"]))
        if any(
            0 < int(rule.get("priority", 0)) <= int(config.TUN_PRIORITY)
            for rule in rules
        ):
            raise RuntimeError(
                "Conflicting early policy rules; refusing to bypass them"
            )
        if table_routes(family):
            raise RuntimeError("Reserved policy routing table already occupied")
    return uplink


def check_user_binding(interface: str) -> None:
    """Local socket-only capability check; no connection or packet is sent."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(
                socket.SOL_SOCKET, socket.SO_BINDTODEVICE, (interface + "\0").encode()
            )
    except OSError as exc:
        raise RuntimeError(
            "Caller cannot bind a fresh transport socket to the uplink; refusing a root engine fallback"
        ) from exc


def configure(owner, uplink: str, uid: int | None = None) -> None:
    tun = config.TUN_NAME
    owner.apply(
        [
            "ip",
            "tuntap",
            "add",
            "dev",
            tun,
            "mode",
            "tun",
            "user",
            str(os.getuid() if uid is None else uid),
        ],
        ["ip", "tuntap", "del", "dev", tun, "mode", "tun"],
    )
    owner.apply(
        ["ip", "address", "add", config.TUN_ADDRESS, "dev", tun],
        ["ip", "address", "del", config.TUN_ADDRESS, "dev", tun],
    )
    owner.apply(
        ["ip", "link", "set", "dev", tun, "mtu", str(config.TUN_MTU), "up"],
        ["ip", "link", "set", "dev", tun, "down"],
    )
    # Loose reverse-path validation on only these links, never a global sysctl.
    for interface in (uplink, tun):
        old = Path(f"/proc/sys/net/ipv4/conf/{interface}/rp_filter").read_text().strip()
        key = f"net/ipv4/conf/{interface}/rp_filter"
        owner.apply(["sysctl", "-w", f"{key}=2"], ["sysctl", "-w", f"{key}={old}"])
    for family in ("-4", "-6"):
        route = (
            ["default", "dev", tun] if family == "-4" else ["unreachable", "default"]
        )
        owner.apply(
            ["ip", family, "route", "add", *route, "table", config.ROUTE_TABLE],
            ["ip", family, "route", "del", *route, "table", config.ROUTE_TABLE],
        )
        # Explicitly uplink-bound IPv4 sockets bypass (required by ConsoleClient).
        # IPv6 is blocked for all nonlocal traffic for this session.
        if family == "-4":
            bypass = [
                "priority",
                config.BYPASS_PRIORITY,
                "oif",
                uplink,
                "lookup",
                "main",
            ]
            owner.apply(
                ["ip", family, "rule", "add", *bypass],
                ["ip", family, "rule", "del", *bypass],
            )
        rule = ["priority", config.TUN_PRIORITY, "lookup", config.ROUTE_TABLE]
        owner.apply(
            ["ip", family, "rule", "add", *rule], ["ip", family, "rule", "del", *rule]
        )
    # Temporarily suppress other links' routing/search domains so ~. is exclusive.
    # Existing private names are deliberately sent through the VPN during use.
    domains = run(["resolvectl", "domain"])
    for line in domains.splitlines():
        match = re.fullmatch(r"Link (\d+) \([^)]*\):\s*(.*)", line.strip())
        if match and match[2].strip():
            link, original = match[1], match[2].split()
            owner.apply(
                ["resolvectl", "domain", link, ""],
                ["resolvectl", "domain", link, *original],
            )
    # Revert precedes restoring other links and deleting the owned TUN.
    owner.apply(
        ["resolvectl", "dns", tun, config.TRANSPARENT_DNS],
        ["resolvectl", "revert", tun],
    )
    owner.apply(["resolvectl", "domain", tun, "~."], ["resolvectl", "revert", tun])
    owner.apply(
        ["resolvectl", "default-route", tun, "yes"], ["resolvectl", "revert", tun]
    )


def verify_route() -> None:
    if active_route().get("dev") != config.TUN_NAME:
        raise RuntimeError("IPv4 route is not the owned TUN; refusing CONNECTED")
