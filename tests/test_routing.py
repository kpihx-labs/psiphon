"""No privileges: inject every route failure and exercise real pipe EOF cleanup."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from psiphon import config, routing, supervisor


def fake_preflight(monkeypatch, domains="", rules=None, routes=None, links=None):
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(routing.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    original_resolve = Path.resolve
    original_exists = Path.exists
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda path, *a, **kw: (
            Path("/run/systemd/resolve/stub-resolv.conf")
            if str(path) == "/etc/resolv.conf"
            else original_resolve(path, *a, **kw)
        ),
    )
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: True if str(path) == "/dev/net/tun" else original_exists(path),
    )

    def query(command):
        if command == ["resolvectl", "domain"]:
            return domains
        if "link" in command:
            return json.dumps(links or [{"ifname": "eth0"}])
        if "rule" in command:
            return json.dumps(rules or [{"priority": 0}, {"priority": 32766}])
        if "get" in command:
            return '[{"dev":"eth0"}]'
        return json.dumps(routes or [])

    monkeypatch.setattr(routing, "run", query)
    monkeypatch.setattr(routing, "table_routes", lambda family: routes or [])


def test_read_only_preflight(monkeypatch):
    fake_preflight(monkeypatch)
    assert routing.preflight() == "eth0"


@pytest.mark.parametrize(
    "domains",
    ["Global: ~.\n", "Link 2 (eth0): corp.example\n", "Link 2 (eth0): ~tail.example\n"],
)
def test_split_dns_preflight_is_read_only(monkeypatch, domains):
    fake_preflight(monkeypatch, domains=domains)
    assert routing.preflight() == "eth0"


def test_conflicting_policy_rule_is_refused(monkeypatch):
    fake_preflight(monkeypatch, rules=[{"priority": 100}])
    with pytest.raises(RuntimeError, match="policy rules"):
        routing.preflight()


def test_occupied_table_is_refused(monkeypatch):
    fake_preflight(monkeypatch, routes=[{"table": int(config.ROUTE_TABLE)}])
    with pytest.raises(RuntimeError, match="table already occupied"):
        routing.preflight()


def test_numeric_table_probe_detects_named_table(monkeypatch):
    mock = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, '[{"table":"reserved-name"}]', ""
        )
    )
    monkeypatch.setattr(routing.subprocess, "run", mock)
    assert routing.table_routes("-4") == [{"table": "reserved-name"}]
    assert mock.call_args.args[0][-1] == config.ROUTE_TABLE


@pytest.mark.parametrize(
    "message,missing",
    [("FIB table does not exist", True), ("Operation not permitted", False)],
)
def test_table_probe_does_not_hide_unexpected_errors(monkeypatch, message, missing):
    monkeypatch.setattr(
        routing.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 2, "[]", message)),
    )
    if missing:
        assert routing.table_routes("-6") == []
    else:
        with pytest.raises(RuntimeError, match="Cannot inspect"):
            routing.table_routes("-6")


def test_occupied_tun_is_refused(monkeypatch):
    fake_preflight(monkeypatch, links=[{"ifname": "eth0"}, {"ifname": config.TUN_NAME}])
    with pytest.raises(RuntimeError, match="reserved TUN"):
        routing.preflight()


def test_unsupported_resolver_is_refused(monkeypatch):
    fake_preflight(monkeypatch)
    monkeypatch.setattr(Path, "resolve", lambda path: Path("/run/other-resolver"))
    with pytest.raises(RuntimeError, match="resolved stub"):
        routing.preflight()


def routing_plan(monkeypatch):
    monkeypatch.setattr(Path, "read_text", lambda path: "1\n")
    monkeypatch.setattr(routing, "run", lambda command: "")
    monkeypatch.setattr(routing, "connected_bridge_routes", list)
    owner = Mock()
    routing.configure(owner, "eth0")
    return [call.args for call in owner.apply.call_args_list]


def test_routing_plan_covers_dns_ipv6_and_engine_bypass(monkeypatch):
    plan = routing_plan(monkeypatch)
    commands = [command for command, undo in plan]
    assert ["resolvectl", "dns", config.TUN_NAME, "10.0.0.2"] in commands
    assert [
        "ip",
        "-6",
        "route",
        "add",
        "unreachable",
        "default",
        "table",
        config.ROUTE_TABLE,
    ] in commands
    assert [
        "ip",
        "-4",
        "rule",
        "add",
        "priority",
        config.BYPASS_PRIORITY,
        "oif",
        "eth0",
        "lookup",
        "main",
    ] in commands
    assert not any(
        "replace" in command or "flush" in command or "sudo" in command
        for command in commands
    )
    sysctls = [command for command in commands if command[0] == "sysctl"]
    assert len(sysctls) == 2 and all("/all/" not in " ".join(cmd) for cmd in sysctls)
    assert any("net/ipv4/conf/eth0/rp_filter=1" in undo for _, undo in plan)


def test_existing_dns_domains_are_restored_verbatim(monkeypatch):
    monkeypatch.setattr(Path, "read_text", lambda path: "2\n")
    monkeypatch.setattr(routing, "connected_bridge_routes", list)
    monkeypatch.setattr(
        routing,
        "run",
        lambda command: (
            "Global: ~private\nLink 3 (tailscale0): tail.example ~.\nLink 2 (eth0): campus.example\n"
        ),
    )
    owner = Mock()
    routing.configure(owner, "eth0")
    calls = [call.args for call in owner.apply.call_args_list]
    assert (
        ["resolvectl", "domain", "3", ""],
        ["resolvectl", "domain", "3", "tail.example", "~."],
    ) in calls
    assert (
        ["resolvectl", "domain", "2", ""],
        ["resolvectl", "domain", "2", "campus.example"],
    ) in calls
    assert not any("Global" in " ".join(command) for command, _ in calls)


@pytest.mark.parametrize("failure", range(13))
def test_rollback_at_every_mutation_boundary(monkeypatch, failure):
    plan = routing_plan(monkeypatch)
    assert len(plan) == 13
    successful = []
    reversed_commands = []
    failed = False

    def command_run(command):
        nonlocal failed
        if not failed and len(successful) == failure:
            failed = True
            raise RuntimeError("injected failure")
        if failed:
            reversed_commands.append(command)
        else:
            successful.append(command)
        return ""

    monkeypatch.setattr(supervisor, "run", command_run)
    transaction = supervisor.Transaction()
    with pytest.raises(RuntimeError, match="injected failure"):
        for command, undo in plan:
            transaction.apply(command, undo)
    assert transaction.close() == []
    assert reversed_commands == [undo for _, undo in reversed(plan[:failure])]


def test_rollback_continues_and_reports_errors(monkeypatch):
    transaction = supervisor.Transaction()
    transaction.undo = [["undo1"], ["undo2"]]
    mock = Mock(side_effect=[RuntimeError("failed undo2"), ""])
    monkeypatch.setattr(supervisor, "run", mock)
    assert transaction.close() == ["failed undo2"]
    assert mock.call_count == 2


def test_mutation_timeout_is_also_rolled_back(monkeypatch):
    transaction = supervisor.Transaction()
    monkeypatch.setattr(
        supervisor, "run", Mock(side_effect=[subprocess.TimeoutExpired("cmd", 1), ""])
    )
    with pytest.raises(subprocess.TimeoutExpired):
        transaction.apply(["cmd"], ["undo"])
    assert transaction.undo == [["undo"]]
    assert transaction.close() == []


def test_supervisor_eof_executes_inverse_offline(tmp_path):
    marker = tmp_path / "marker"

    def write(text):
        return [
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).write_text({text!r})",
        ]

    with supervisor.Supervisor() as owner:
        owner.apply(write("applied"), write("reverted"))
        assert marker.read_text() == "applied"
    assert marker.read_text() == "reverted"


def test_real_controller_sigkill_triggers_guardian_rollback(tmp_path):
    marker = tmp_path / "rollback"
    # No live engine, root, network or polling. The subprocess models a controller.
    script = (
        "import sys, json; from psiphon.supervisor import Supervisor; "
        "s=Supervisor(); "
        f"s.apply([sys.executable,'-c','pass'], [sys.executable,'-c',"
        f"{('from pathlib import Path; Path(' + repr(str(marker)) + ').write_text("done")')!r}]); "
        f"pid=s.request('start',command=[sys.executable,'-c','import signal; signal.pause()'],log={str(tmp_path / 'dummy.log')!r}); "
        "print(json.dumps([s.process.pid,pid]), flush=True); sys.stdin.readline()"
    )
    controller = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert controller.stdout is not None
    try:
        _guardian, pid = json.loads(controller.stdout.readline())
        os.kill(controller.pid, signal.SIGKILL)
        # The guardian inherits stderr. communicate waits for its EOF, not a poll.
        _, errors = controller.communicate(timeout=15)
        assert errors == ""
        assert marker.read_text() == "done"
        assert not Path(f"/proc/{pid}").exists()
    finally:
        if controller.poll() is None:
            controller.kill()
        controller.communicate(timeout=5)


def test_engine_stopped_on_context_exit(tmp_path):
    # A blocked stdin read is sufficient to model a long-lived engine.
    # Engine stdin is DEVNULL, so use a signal wait instead of a sleep/poll loop.
    with supervisor.Supervisor() as owner:
        pid = owner.request(
            "start",
            command=[sys.executable, "-c", "import signal; signal.pause()"],
            log=str(tmp_path / "engine.log"),
        )
        assert owner.request("poll") is None
    assert not Path(f"/proc/{pid}").exists()


def test_only_direct_bridge_prefixes_bypass_tun(monkeypatch):
    links = [
        {"ifname": "br-test", "linkinfo": {"info_kind": "bridge"}},
        {"ifname": "wifi", "linkinfo": {"info_kind": "ether"}},
    ]
    routes = [
        # Real `ip -j route show ... scope link` omits the scope property.
        {"dst": "172.18.0.0/16", "dev": "br-test"},
        {"dst": "192.168.1.0/24", "dev": "wifi", "scope": "link"},
        {
            "dst": "default",
            "dev": "br-test",
            "gateway": "172.18.0.1",
            "scope": "global",
        },
        {
            "dst": "10.0.0.0/8",
            "dev": "br-test",
            "gateway": "172.18.0.1",
            "scope": "link",
        },
    ]
    monkeypatch.setattr(
        routing,
        "run",
        lambda command: json.dumps(
            links if "link" in command and "-d" in command else routes
        ),
    )
    assert routing.connected_bridge_routes() == [
        {"dst": "172.18.0.0/16", "dev": "br-test"}
    ]


def test_bridge_route_mutation_is_owned_and_reversed(monkeypatch):
    routing_plan(monkeypatch)
    monkeypatch.setattr(
        routing,
        "connected_bridge_routes",
        lambda: [{"dst": "172.18.0.0/16", "dev": "br-test"}],
    )
    owner = Mock()
    routing.configure(owner, "eth0")
    calls = [call.args for call in owner.apply.call_args_list]
    direct = [
        "172.18.0.0/16",
        "dev",
        "br-test",
        "scope",
        "link",
        "table",
        config.ROUTE_TABLE,
    ]
    assert (
        ["ip", "-4", "route", "add", *direct],
        ["ip", "-4", "route", "del", *direct],
    ) in calls
