"""Foreground CLI. Network mutation belongs exclusively to the pipe supervisor."""

import fcntl
import functools
import json
import os
import signal
import socket
import subprocess
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any

import requests
import typer
from rich.console import Console

from psiphon import config, engine, network, routing
from psiphon.supervisor import RollbackError, Supervisor

app = typer.Typer(
    help="Foreground native Psiphon VPN; choose --proxy for local proxies only.",
    no_args_is_help=True,
    invoke_without_command=True,
    add_completion=False,
    context_settings={"help_option_names": ["--help", "-h"]},
)
console = Console()


def boundary(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (
            OSError,
            RuntimeError,
            ValueError,
            ConnectionError,
            subprocess.SubprocessError,
            requests.RequestException,
        ) as exc:
            console.print(f"Error: {exc}", markup=False)
            raise typer.Exit(1) from exc

    return wrapped


@app.callback()
def options(
    show_version: bool = typer.Option(False, "--version", "-v", is_eager=True),
) -> None:
    if show_version:
        console.print(version("psiphon"))
        raise typer.Exit()


def region_code(value: str) -> str:
    if value and (len(value) != 2 or not value.isascii() or not value.isalpha()):
        raise typer.BadParameter("Use a two-letter ASCII region code")
    return value.upper()


def proxy_url(enabled: bool) -> str | None:
    return f"http://{config.PROXY_HOST}:{config.HTTP_PROXY_PORT}" if enabled else None


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((config.PROXY_HOST, port)) == 0


def notice_state(offset: int = 0) -> dict[str, Any]:
    state: dict[str, Any] = {
        "tunnels": 0,
        "region": None,
        "regions": [],
        "packet": False,
    }
    try:
        with config.LOG_FILE.open() as log:
            log.seek(offset)
            for line in log:
                try:
                    notice = json.loads(line)
                except json.JSONDecodeError:
                    continue
                data = notice.get("data", {})
                kind = notice.get("noticeType")
                if kind == "Tunnels":
                    state["tunnels"] = data.get("count", 0)
                    if not state["tunnels"]:
                        state["packet"] = False
                        state["region"] = None
                elif kind == "ConnectedServerRegion":
                    state["region"] = data.get("serverRegion")
                elif kind == "AvailableEgressRegions":
                    state["regions"] = data.get("regions", [])
                elif (
                    kind == "Info"
                    and "DialPacketTunnelChannel: established channel"
                    in str(data.get("message", ""))
                ):
                    state["packet"] = True
    except FileNotFoundError:
        pass
    return state


def process_identity(pid: int) -> dict[str, str]:
    proc = Path(f"/proc/{pid}")
    stat = (proc / "stat").read_text().rsplit(") ", 1)[1].split()
    if pid <= 1 or stat[0] == "Z" or proc.stat().st_uid != os.getuid():
        raise RuntimeError("Process is not an owned live controller")
    return {"start": stat[19], "command": (proc / "cmdline").read_bytes().hex()}


@contextmanager
def session_lock():
    engine.ensure_state()
    fd = os.open(
        config.RUNTIME_DIR / "session.lock",
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "A controller is already running; stop it first"
            ) from exc
        try:
            yield
        finally:
            config.SESSION_FILE.unlink(missing_ok=True)


@contextmanager
def termination_handler():
    def terminate(signum, frame):
        raise InterruptedError("Session terminated; rolling back")

    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


@contextmanager
def connected(region: str, proxy: bool, interface: str | None, wait_s: float):
    engine.verify()
    with session_lock(), termination_handler():
        uplink = None if proxy else routing.preflight(interface)
        if uplink:
            routing.check_user_binding(uplink)
        if proxy:
            for port in (config.HTTP_PROXY_PORT, config.SOCKS_PROXY_PORT):
                if port_open(port):
                    raise RuntimeError(
                        f"PORT {port} ALREADY IN USE; refusing to steal it"
                    )
        elif interface:
            uplink = interface
        engine.write_config(region, proxy)
        # Create a private log before the worker opens it; never truncate history.
        fd = os.open(
            config.LOG_FILE,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW,
            0o600,
        )
        os.close(fd)
        offset = config.LOG_FILE.stat().st_size
        with Supervisor(native=not proxy) as owner:
            if uplink:
                owner.request("configure", interface=uplink)
                pid = owner.request(
                    "start",
                    binary=str(config.BINARY),
                    config=str(config.ACTIVE_CONFIG),
                    data=str(config.DATA_DIR),
                    log=str(config.LOG_FILE),
                )
            else:
                pid = owner.request(
                    "start", command=engine.command(), log=str(config.LOG_FILE)
                )
            engine.atomic_write(
                config.SESSION_FILE,
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "identity": process_identity(os.getpid()),
                        "engine_pid": pid,
                        "mode": "proxy" if proxy else "tun",
                        "region": region,
                    }
                ).encode(),
            )
            deadline = time.monotonic() + wait_s
            verified = None
            while time.monotonic() < deadline:
                if owner.request("poll") is not None:
                    break
                state = notice_state(offset)
                if state["tunnels"] > 0 and state["region"]:
                    if region and state["region"] != region:
                        raise RuntimeError(
                            f"Wrong reported region: {state['region']}, wanted {region}"
                        )
                    if proxy or state["packet"]:
                        try:
                            if not proxy:
                                routing.verify_route()
                            verified = network.public_ip(proxy_url(proxy), timeout=2)
                            break
                        except (ConnectionError, requests.RequestException):
                            pass
                time.sleep(0.25)
            if not verified or owner.request("poll") is not None:
                raise RuntimeError(
                    f"CONNECTION FAILED ({region or 'automatic'}): no verified "
                    f"{'proxy' if proxy else 'packet-tunnel'} path within {wait_s}s. "
                    f"Not every exit supports packet tunnels. Log: {config.LOG_FILE}"
                )
            yield owner, verified, offset


@app.command()
@boundary
def setup() -> None:
    """Download and hash-verify the pinned official engine into XDG data."""
    engine.setup()
    console.print(f"Verified engine: {config.BINARY}", markup=False)


@app.command()
@boundary
def doctor(
    proxy: bool = typer.Option(
        False, "--proxy", "-p", help="Check proxy requirements only"
    ),
    interface: str | None = typer.Option(None, "--interface", "-i"),
) -> None:
    """Offline/read-only preflight; never downloads or changes networking."""
    engine.verify()
    console.print(f"Engine hash OK: {config.ENGINE_SHA256}")
    if proxy:
        busy = [
            p for p in (config.HTTP_PROXY_PORT, config.SOCKS_PROXY_PORT) if port_open(p)
        ]
        if busy:
            raise RuntimeError(f"Proxy ports occupied: {busy}")
    else:
        uplink = routing.preflight(interface)
        routing.check_user_binding(uplink)
        console.print(
            f"TUN preflight OK; bypass interface: {uplink}. Connect will request sudo for its network supervisor."
        )
    console.print(
        "Offline preflight passed; fleet/packet-channel availability is untested."
    )


@app.command()
@boundary
def connect(
    region: str = typer.Option(
        "", "--region", "-r", help="ISO region; empty lets engine choose"
    ),
    proxy: bool = typer.Option(
        False, "--proxy", "-p", help="Local HTTP/SOCKS only; no route changes"
    ),
    interface: str | None = typer.Option(
        None, "--interface", "-i", help="Physical bypass interface"
    ),
    wait_s: float = typer.Option(config.CONNECT_WAIT_S, "--wait", "-w", min=1, max=300),
) -> None:
    """Run a foreground native packet tunnel until Ctrl-C (or explicit proxy)."""
    region = region_code(region)
    if proxy and interface:
        raise typer.BadParameter("--interface is only meaningful in native TUN mode")
    with connected(region, proxy, interface, wait_s) as (owner, address, _offset):
        console.print(
            f"CONNECTED: {'proxy only' if proxy else 'native TUN'}; HTTPS IP {address}. Ctrl-C stops and rolls back."
        )
        if proxy:
            console.print(
                f"HTTP {config.PROXY_HOST}:{config.HTTP_PROXY_PORT}; SOCKS {config.PROXY_HOST}:{config.SOCKS_PROXY_PORT}"
            )
        while owner.request("poll") is None:
            time.sleep(0.5)
        raise RuntimeError("Engine exited; session rolled back")


@app.command()
@boundary
def disconnect() -> None:
    """Ask the owned foreground controller to terminate and roll back."""
    if not config.SESSION_FILE.exists():
        console.print("No owned session for this user; use Ctrl-C in its terminal.")
        return
    if (
        config.RUNTIME_DIR.is_symlink()
        or config.SESSION_FILE.is_symlink()
        or config.RUNTIME_DIR.stat().st_uid != os.getuid()
    ):
        raise PermissionError("Refusing unsafe session metadata")
    data = json.loads(config.SESSION_FILE.read_text())
    pid = int(data["pid"])
    if process_identity(pid) != data["identity"]:
        raise RuntimeError("Stale process identity; no signal sent")
    os.kill(pid, signal.SIGTERM)
    console.print("Termination requested; controller performs rollback before exiting.")


@app.command()
@boundary
def regions() -> None:
    """Show catalogue plus last fleet notice, not guaranteed packet support."""
    fleet = notice_state()["regions"]
    for code in sorted(set(config.REGIONS) | set(fleet)):
        console.print(
            f"{code}  {config.REGIONS.get(code, code)}  {'last fleet notice' if code in fleet else 'catalogue only'}"
        )
    console.print("A proxy-capable region is not proof of packet-tunnel support.")


@app.command()
@boundary
def status(
    proxy: bool = typer.Option(
        False,
        "--proxy",
        "-p",
        help="Measure explicit local proxy instead of active OS route",
    ),
    geo: bool = typer.Option(
        False,
        "--geo",
        "-g",
        help="Query third-party GeoIP (not physical-location proof)",
    ),
    download: bool = typer.Option(False, "--download", "-d"),
    upload: bool = typer.Option(False, "--upload", "-u"),
    speed: bool = typer.Option(
        False, "--speed", "-s", help="Measure download and upload explicitly"
    ),
    seconds: float = typer.Option(
        config.BENCH_DEFAULT_S, "--seconds", "-n", min=1, max=60
    ),
) -> None:
    """Inspect the current route and HTTPS egress, even without Psiphon running."""
    route = routing.active_route()
    console.print("Active OS route: " + json.dumps(route), markup=False)
    transport = proxy_url(proxy)
    address = network.public_ip(transport)
    console.print(
        f"{'Explicit proxy' if proxy else 'Active route'} HTTPS IP: {address}"
    )
    if geo:
        console.print(network.geo(address, transport))
    for enabled, name, measure in (
        (download or speed, "download", network.download),
        (upload or speed, "upload", network.upload),
    ):
        if enabled:
            result = measure(seconds, transport)
            console.print(
                f"{name}: {result.mbps:.3f} Mbps; {result.bytes_received} bytes / {result.elapsed_s:.3f}s"
            )


@app.command()
@boundary
def bench(
    all_regions: bool = typer.Option(
        False, "--all", "-a", help="Explicitly survey catalogue + observed fleet"
    ),
    region: Annotated[
        list[str] | None,
        typer.Option("--region", "-r", help="Repeat for selected regions"),
    ] = None,
    proxy: bool = typer.Option(False, "--proxy", "-p"),
    upload: bool = typer.Option(False, "--upload", "-u"),
    seconds: float = typer.Option(
        config.BENCH_DEFAULT_S, "--seconds", "-s", min=1, max=60
    ),
    wait_s: float = typer.Option(config.CONNECT_WAIT_S, "--wait", "-w", min=1, max=300),
) -> None:
    """Explicit live region survey; each attempt and failure is private JSONL."""
    if all_regions == bool(region):
        raise typer.BadParameter("Choose --all/-a OR one or more --region/-r")
    selected = {region_code(code) for code in region or []}
    if all_regions:
        selected.update(config.REGIONS)
        selected.update(notice_state()["regions"])
    engine.verify()
    if not proxy:
        routing.preflight()
    engine.ensure_state()
    engine.private_directory(config.CACHE_DIR)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    path = config.CACHE_DIR / f"bench-{stamp}.jsonl"
    console.print(f"Observations: {path}", markup=False)
    attempted: set[str] = set()
    with open(path, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as log:
        while selected - attempted:
            code = min(selected - attempted)
            attempted.add(code)
            result: dict[str, Any] = {
                "region": code,
                "mode": "proxy" if proxy else "tun",
            }
            try:
                with connected(code, proxy, None, wait_s) as (_, address, offset):
                    result["exit_ip"] = address
                    result["reported_region"] = notice_state(offset)["region"]
                    result["download_mbps"] = network.download(
                        seconds, proxy_url(proxy)
                    ).mbps
                    if upload:
                        result["upload_mbps"] = network.upload(
                            seconds, proxy_url(proxy)
                        ).mbps
            except (
                OSError,
                RuntimeError,
                ValueError,
                ConnectionError,
                subprocess.SubprocessError,
                requests.RequestException,
            ) as exc:
                if isinstance(exc, RollbackError):
                    result["error"] = str(exc)
                    log.write(json.dumps(result) + "\n")
                    log.flush()
                    raise  # Never stack another session on incomplete cleanup.
                result["error"] = str(exc)
            if all_regions:
                selected.update(notice_state()["regions"])
            log.write(json.dumps(result) + "\n")
            log.flush()
            console.print(result)
        log.write(
            json.dumps({"selected": sorted(selected), "attempted": sorted(attempted)})
            + "\n"
        )
    console.print(
        f"Coverage: {len(attempted)}/{len(selected)} attempts; failures are not zero bandwidth."
    )


if __name__ == "__main__":
    app()
