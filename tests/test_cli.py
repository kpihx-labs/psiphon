"""Offline CLI, engine installation, network-boundary and lifecycle regressions."""

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from typer.testing import CliRunner

from psiphon import config, engine, main, network

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for key, relative in {
        "CONFIG_DIR": "config",
        "STATE_DIR": "state",
        "CACHE_DIR": "cache",
        "DATA_DIR": "cache/core",
        "RUNTIME_DIR": "runtime",
        "ENGINE_DIR": "engine",
        "BINARY": "engine/core",
        "ACTIVE_CONFIG": "config/psiphon.config",
        "LOG_FILE": "state/psiphon.log",
        "SESSION_FILE": "runtime/session.json",
    }.items():
        monkeypatch.setattr(config, key, tmp_path / relative)


def test_help_and_short_help():
    for arguments in (["-h"], ["--help"]):
        result = runner.invoke(main.app, arguments)
        assert result.exit_code == 0, result.output
        for command in (
            "setup",
            "doctor",
            "connect",
            "disconnect",
            "status",
            "bench",
            "regions",
        ):
            assert command in result.output
        assert "service" not in result.output


def test_version_without_subcommand():
    result = runner.invoke(main.app, ["-v"])
    assert result.exit_code == 0, result.output
    assert main.version("psiphon") in result.output


@pytest.mark.parametrize("command", ["connect", "doctor", "status", "bench"])
def test_every_public_option_has_short_alias(command):
    import typer.main

    click_command = typer.main.get_command(main.app).commands[command]
    for param in click_command.params:
        assert any(
            option.startswith("-") and not option.startswith("--")
            for option in param.opts
        ), param.name


def test_invalid_region_fails_before_engine_access():
    assert runner.invoke(main.app, ["connect", "-r", "invalid"]).exit_code == 2


def test_connect_is_foreground_native_by_default(monkeypatch):
    captured = []

    @contextmanager
    def connection(region, proxy, interface, wait_s):
        captured.append((region, proxy, interface))
        yield Mock(request=Mock(return_value=0)), "192.0.2.1", 0

    monkeypatch.setattr(main, "connected", connection)
    result = runner.invoke(main.app, ["connect", "-r", "fr"])
    assert captured == [("FR", False, None)]
    assert "native TUN" in result.output
    assert result.exit_code == 1  # unexpected engine exit is not success


def test_explicit_proxy_and_busy_port(monkeypatch):
    monkeypatch.setattr(engine, "verify", lambda: None)
    monkeypatch.setattr(main, "port_open", lambda port: True)
    monkeypatch.setattr(
        main.routing, "preflight", Mock(side_effect=AssertionError("No route access"))
    )
    result = runner.invoke(main.app, ["connect", "-p", "-r", "FR"])
    assert result.exit_code == 1
    assert "ALREADY IN USE" in result.output


def test_native_requests_only_elevated_supervisor_and_keeps_user_state(monkeypatch):
    monkeypatch.setattr(engine, "verify", lambda: None)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.setattr(main.routing, "preflight", lambda interface: "eth0")
    monkeypatch.setattr(main.routing, "check_user_binding", lambda interface: None)
    monkeypatch.setattr(main.routing, "verify_route", lambda: None)
    monkeypatch.setattr(
        main,
        "notice_state",
        lambda offset: {"tunnels": 1, "region": "DE", "packet": True},
    )
    monkeypatch.setattr(network, "public_ip", lambda *a, **kw: "192.0.2.1")
    owner = Mock()
    owner.request.side_effect = lambda op, **kw: 123 if op == "start" else None
    wrapper = Mock(
        __enter__=Mock(return_value=owner), __exit__=Mock(return_value=False)
    )
    factory = Mock(return_value=wrapper)
    monkeypatch.setattr(main, "Supervisor", factory)
    with main.connected("DE", False, None, 1):
        factory.assert_called_once_with(native=True)
        start = next(
            call for call in owner.request.call_args_list if call.args == ("start",)
        )
        assert start.kwargs["binary"] == str(config.BINARY)
        assert start.kwargs["config"] == str(config.ACTIVE_CONFIG)
        assert start.kwargs["data"] == str(config.DATA_DIR)
        assert "command" not in start.kwargs
        assert config.SESSION_FILE.stat().st_uid == os.getuid()
    wrapper.__exit__.assert_called_once()


def test_preferences_and_native_config():
    engine.ensure_state()
    engine.write_config("FR", True)
    data = json.loads(config.ACTIVE_CONFIG.read_text())
    data["ConnectionWorkerPoolSize"] = 4
    config.ACTIVE_CONFIG.write_text(json.dumps(data))
    engine.write_config("JP", False)
    data = json.loads(config.ACTIVE_CONFIG.read_text())
    assert data["ConnectionWorkerPoolSize"] == 4
    assert data["EgressRegion"] == "JP"
    assert data["DisableLocalHTTPProxy"] is True
    assert data["DisableLocalSocksProxy"] is True
    assert data["TunnelPoolSize"] == 1
    assert data["ListenInterface"] == ""
    assert data["SplitTunnelRegions"] == []
    assert config.ACTIVE_CONFIG.stat().st_mode & 0o777 == 0o600


def test_command_has_official_tun_flags():
    command = engine.command("eth0")
    for value in (
        "-tunDevice",
        config.TUN_NAME,
        "-tunBindInterface",
        "eth0",
        "-tunDNSServers",
        config.BYPASS_DNS,
    ):
        assert value in command
    assert "-tunDevice" not in engine.command()


def test_foreign_runtime_symlink_is_rejected(tmp_path):
    target = tmp_path / "foreign"
    target.mkdir()
    config.RUNTIME_DIR.symlink_to(target, target_is_directory=True)
    with pytest.raises(PermissionError):
        engine.ensure_state()


def test_lock_prevents_concurrent_controller():
    with (
        main.session_lock(),
        pytest.raises(RuntimeError, match="already running"),
        main.session_lock(),
    ):
        pytest.fail("Second session acquired lock")


def test_disconnect_rejects_reused_identity(monkeypatch):
    engine.ensure_state()
    config.SESSION_FILE.write_text(
        json.dumps({"pid": os.getpid(), "identity": {"start": "old"}})
    )
    kill = Mock()
    monkeypatch.setattr(os, "kill", kill)
    result = runner.invoke(main.app, ["disconnect"])
    assert result.exit_code == 1
    kill.assert_not_called()


def test_notice_channel_and_fresh_offset():
    engine.ensure_state()
    config.LOG_FILE.write_text(
        json.dumps({"noticeType": "Tunnels", "data": {"count": 1}}) + "\n"
    )
    offset = config.LOG_FILE.stat().st_size
    with config.LOG_FILE.open("a") as log:
        for kind, data in (
            ("AvailableEgressRegions", {"regions": ["FR", "JP"]}),
            ("ConnectedServerRegion", {"serverRegion": "JP"}),
            ("Info", {"message": "DialPacketTunnelChannel: established channel"}),
        ):
            log.write(json.dumps({"noticeType": kind, "data": data}) + "\n")
    state = main.notice_state(offset)
    assert state == {
        "tunnels": 0,
        "region": "JP",
        "regions": ["FR", "JP"],
        "packet": True,
    }
    assert main.notice_state()["tunnels"] == 1


@pytest.mark.parametrize(
    "packet,proxy,expected",
    [(False, False, False), (True, False, True), (False, True, True)],
)
def test_readiness_requires_packet_channel_in_native_mode(
    monkeypatch, packet, proxy, expected
):
    monkeypatch.setattr(engine, "verify", lambda: None)
    monkeypatch.setattr(main.routing, "preflight", lambda interface: "eth0")
    monkeypatch.setattr(main.routing, "configure", lambda owner, uplink: None)
    monkeypatch.setattr(main.routing, "check_user_binding", lambda uplink: None)
    monkeypatch.setattr(main.routing, "verify_route", lambda: None)
    monkeypatch.setattr(main, "port_open", lambda port: False)
    monkeypatch.setattr(
        main,
        "notice_state",
        lambda offset: {"tunnels": 1, "region": "FR", "packet": packet},
    )
    monotonic = iter([0, 0, 2])
    monkeypatch.setattr(main.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(main.time, "sleep", lambda seconds: None)
    check = Mock(return_value="192.0.2.1")
    monkeypatch.setattr(network, "public_ip", check)
    owner = Mock()
    owner.request.side_effect = lambda op, **kw: 123 if op == "start" else None
    wrapper = Mock(
        __enter__=Mock(return_value=owner), __exit__=Mock(return_value=False)
    )
    monkeypatch.setattr(main, "Supervisor", lambda **kwargs: wrapper)
    if expected:
        with main.connected("FR", proxy, None, 1) as (_, address, _offset):
            assert address == "192.0.2.1"
    else:
        with (
            pytest.raises(RuntimeError, match="CONNECTION FAILED"),
            main.connected("FR", proxy, None, 1),
        ):
            pytest.fail("Native mode accepted proxy-only readiness")
        check.assert_not_called()
    wrapper.__exit__.assert_called_once()
    assert not config.SESSION_FILE.exists()


def test_status_is_generic_and_has_no_implicit_speed_or_geo(monkeypatch):
    monkeypatch.setattr(main.routing, "active_route", lambda: {"dev": "other-vpn"})
    check = Mock(return_value="192.0.2.1")
    monkeypatch.setattr(network, "public_ip", check)
    for name in ("download", "upload", "geo"):
        monkeypatch.setattr(
            network, name, Mock(side_effect=AssertionError("Not opted in"))
        )
    result = runner.invoke(main.app, ["status"])
    assert result.exit_code == 0, result.output
    assert "other-vpn" in result.output
    check.assert_called_once_with(None)


def test_status_optional_measurements(monkeypatch):
    monkeypatch.setattr(main.routing, "active_route", lambda: {"dev": "eth0"})
    monkeypatch.setattr(network, "public_ip", lambda proxy: "192.0.2.1")
    geo = Mock(return_value={"country_code": "FR"})
    monkeypatch.setattr(network, "geo", geo)
    for name in ("download", "upload"):
        monkeypatch.setattr(
            network, name, Mock(return_value=network.Measurement(3, 100, 1, 0.1))
        )
    result = runner.invoke(main.app, ["status", "-p", "-g", "-s", "-n", "1"])
    assert result.exit_code == 0, result.output
    assert "Download" in result.output and "Upload" in result.output
    geo.assert_called_once_with("192.0.2.1", main.proxy_url(True))


def test_bench_requires_explicit_scope():
    assert runner.invoke(main.app, ["bench"]).exit_code == 2
    assert runner.invoke(main.app, ["bench", "-a", "-r", "FR"]).exit_code == 2


def test_bench_all_covers_catalogue_and_new_announcements(monkeypatch):
    monkeypatch.setattr(engine, "verify", lambda: None)
    monkeypatch.setattr(config, "REGIONS", {"FR": "France", "JP": "Japan"})
    monkeypatch.setattr(
        main, "notice_state", lambda *a: {"regions": ["DE"], "region": "FR"}
    )
    attempted = []

    @contextmanager
    def connect(code, proxy, interface, wait_s):
        attempted.append(code)
        if code == "JP":
            raise ConnectionError("unavailable")
        yield Mock(), "192.0.2.1", 0

    monkeypatch.setattr(main, "connected", connect)
    monkeypatch.setattr(
        network, "download", lambda *a: network.Measurement(1, 100, 1, 0.1)
    )
    result = runner.invoke(main.app, ["bench", "-a", "-p", "-s", "1"])
    assert result.exit_code == 0, result.output
    assert set(attempted) == {"FR", "JP", "DE"}
    path = next(config.CACHE_DIR.glob("bench-*.jsonl"))
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[-1]["attempted"] == rows[-1]["selected"]
    failed = next(row for row in rows[:-1] if row["region"] == "JP")
    assert "error" in failed and "download_mbps" not in failed
    assert path.stat().st_mode & 0o777 == 0o600


def test_bench_stops_after_rollback_failure(monkeypatch):
    from psiphon.supervisor import RollbackError

    monkeypatch.setattr(engine, "verify", lambda: None)
    attempted = []

    @contextmanager
    def connect(code, proxy, interface, wait_s):
        attempted.append(code)
        raise RollbackError("cleanup failed")
        yield

    monkeypatch.setattr(main, "connected", connect)
    result = runner.invoke(main.app, ["bench", "-p", "-r", "FR", "-r", "JP"])
    assert result.exit_code == 1
    assert attempted == ["FR"]


def test_setup_refuses_symlink_without_modifying_target(tmp_path):
    engine.private_directory(config.ENGINE_DIR)
    target = tmp_path / "foreign"
    target.write_bytes(b"foreign data")
    config.BINARY.symlink_to(target)
    with pytest.raises(PermissionError, match="symlinked"):
        engine.setup()
    assert target.read_bytes() == b"foreign data"


def mock_session(monkeypatch, response):
    client = Mock()
    client.get.return_value = response
    client.post.return_value = response
    wrapper = Mock(
        __enter__=Mock(return_value=client), __exit__=Mock(return_value=False)
    )
    monkeypatch.setattr(network, "session", lambda proxy=None: wrapper)
    return client


def test_proxy_environment_not_inherited(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://foreign.invalid:1")
    with network.session("http://127.0.0.1:18081") as client:
        assert not client.trust_env
        assert client.proxies["https"] == "http://127.0.0.1:18081"
    with network.session() as client:
        assert not client.proxies


def test_html_is_not_a_public_ip(monkeypatch):
    mock_session(monkeypatch, Mock(text="<html>blocked</html>"))
    with pytest.raises(ConnectionError):
        network.public_ip()


@pytest.mark.parametrize("seconds", [-1, 0, 61])
@pytest.mark.parametrize("measure", [network.download, network.upload])
def test_speed_duration_bounds(measure, seconds):
    with pytest.raises(ValueError):
        measure(seconds)


def test_upload_counts_payload_and_requires_success(monkeypatch):
    client = mock_session(monkeypatch, Mock())

    def post(url, data, **kw):
        for chunk in data:
            assert len(chunk) <= 65536
        return Mock()

    client.post.side_effect = post
    measurement = network.upload(1)
    assert measurement.bytes_received == 40_000_000
    assert measurement.mbps > 0
    client.post.side_effect = requests.ConnectionError("failed")
    with pytest.raises(requests.ConnectionError):
        network.upload(1)


def test_setup_hash_failure_does_not_replace_engine(monkeypatch):
    engine.private_directory(config.ENGINE_DIR)
    config.BINARY.write_bytes(b"old")
    response = Mock()
    response.iter_content.return_value = [b"corrupt"]
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    mock_session(monkeypatch, response)
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        engine.setup()
    assert config.BINARY.read_bytes() == b"old"


def test_setup_installs_verified_engine_and_exact_license(monkeypatch):
    payload = b"verified test payload"
    monkeypatch.setattr(config, "ENGINE_SHA256", hashlib.sha256(payload).hexdigest())
    response = Mock()
    response.iter_content.return_value = [payload]
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    client = mock_session(monkeypatch, response)
    engine.setup()
    assert config.BINARY.read_bytes() == payload
    assert config.BINARY.stat().st_mode & 0o777 == 0o700
    assert (
        config.ENGINE_DIR / "LICENSE"
    ).read_bytes() == config.ENGINE_LICENSE.read_bytes()
    client.get.assert_called_once()
    engine.setup()
    client.get.assert_called_once()  # idempotent, no second download


def test_license_resources_and_canonical_busl_body():
    root = Path(__file__).resolve().parents[1]
    canonical = Path.home() / ".agents/skills/k-project/assets/licenses/BUSL-1.1.txt"
    if canonical.exists():
        assert (
            root.joinpath("LICENSE").read_text().split("Terms\n", 1)[1]
            == canonical.read_text().split("Terms\n", 1)[1]
        )
    assert engine.digest(config.ENGINE_LICENSE) == config.ENGINE_LICENSE_SHA256


def test_contract_metadata_matches_document():
    import tomllib

    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text())["tool"][
        "psiphon-contract"
    ]
    text = (root / "CONTRACT.md").read_text()
    assert metadata["schema_version"] in text and metadata["contract_version"] in text
