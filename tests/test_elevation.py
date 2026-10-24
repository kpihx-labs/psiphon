"""No root/sudo execution: elevated-path tests use real user files and mocked spawn."""

import fcntl
import hashlib
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from psiphon import config, engine, routing, supervisor


def test_sudo_authentication_is_separate_from_protocol_pipe(monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 1234)
    monkeypatch.setattr(supervisor.shutil, "which", lambda name: "/usr/bin/sudo")
    auth = Mock()
    spawn = Mock()
    monkeypatch.setattr(supervisor.subprocess, "run", auth)
    monkeypatch.setattr(supervisor.subprocess, "Popen", spawn)
    supervisor.Supervisor(native=True)
    auth.assert_called_once_with(["/usr/bin/sudo", "-v"], check=True)
    command = spawn.call_args.args[0]
    assert command[:3] == ["/usr/bin/sudo", "-n", "--"]
    assert command[3:6] == [sys.executable, "-I", "-c"]
    assert "worker(native=True)" in command[6]
    assert spawn.call_args.kwargs["start_new_session"] is False  # sudo tty ticket
    assert spawn.call_args.kwargs["stdin"] == supervisor.subprocess.PIPE
    assert (
        "env" not in spawn.call_args.kwargs
    )  # no preserved user PYTHONPATH/XDG to root


def test_proxy_supervisor_never_authenticates(monkeypatch):
    auth = Mock(side_effect=AssertionError("No elevation in proxy mode"))
    spawn = Mock()
    monkeypatch.setattr(supervisor.subprocess, "run", auth)
    monkeypatch.setattr(supervisor.subprocess, "Popen", spawn)
    supervisor.Supervisor()
    auth.assert_not_called()
    assert spawn.call_args.args[0] == [sys.executable, "-m", "psiphon.supervisor"]
    assert spawn.call_args.kwargs["start_new_session"] is True


def test_missing_sudo_fails_without_root_shell_fallback(monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 1234)
    monkeypatch.setattr(supervisor.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="needs sudo"):
        supervisor.Supervisor(native=True)


def test_cancelled_authentication_never_starts_worker(monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 1234)
    monkeypatch.setattr(supervisor.shutil, "which", lambda name: "/usr/bin/sudo")
    monkeypatch.setattr(
        supervisor.subprocess,
        "run",
        Mock(side_effect=supervisor.subprocess.CalledProcessError(1, "sudo")),
    )
    spawn = Mock()
    monkeypatch.setattr(supervisor.subprocess, "Popen", spawn)
    with pytest.raises(supervisor.subprocess.CalledProcessError):
        supervisor.Supervisor(native=True)
    spawn.assert_not_called()


def fake_engine(tmp_path, monkeypatch):
    binary = tmp_path / "core"
    payload = b"not executed test artifact"
    binary.write_bytes(payload)
    binary.chmod(0o700)
    monkeypatch.setattr(config, "ENGINE_SHA256", hashlib.sha256(payload).hexdigest())
    return binary, payload


def test_sealed_snapshot_cannot_change_after_hash(tmp_path, monkeypatch):
    binary, payload = fake_engine(tmp_path, monkeypatch)
    fd = engine.sealed_engine(str(binary), os.getuid())
    try:
        binary.write_bytes(b"changed after verification")
        assert os.read(fd, len(payload)) == payload
        with pytest.raises(PermissionError):
            os.write(fd, b"injection")
        seals = fcntl.fcntl(fd, engine.F_GET_SEALS)
        assert seals & engine.F_SEAL_WRITE and seals & engine.F_SEAL_SEAL
    finally:
        os.close(fd)


def test_privileged_hash_does_not_trust_requested_hash(tmp_path, monkeypatch):
    binary, _ = fake_engine(tmp_path, monkeypatch)
    binary.write_bytes(b"modified before verification")
    with pytest.raises(RuntimeError, match="Elevated engine SHA-256 mismatch"):
        engine.sealed_engine(str(binary), os.getuid())


def test_user_config_group_shared_base_is_not_a_root_setup_requirement(
    tmp_path, monkeypatch
):
    base = tmp_path / "user-config-base"
    base.mkdir(mode=0o775)
    base.chmod(0o775)
    active = base / "config"
    active.write_bytes(b"user configuration")
    active.chmod(0o600)
    fd = engine.open_user_path(str(active), os.getuid())
    os.close(fd)
    binary, _ = fake_engine(base, monkeypatch)
    with pytest.raises(PermissionError, match="Unsafe path ancestor"):
        engine.sealed_engine(str(binary), os.getuid())


@pytest.mark.parametrize(
    "kind", ["symlink", "writable", "foreign-owner", "relative", "parent-symlink"]
)
def test_privileged_open_rejects_unsafe_paths(tmp_path, kind):
    target = tmp_path / "target"
    target.write_bytes(b"data")
    uid = os.getuid()
    if kind == "symlink":
        path = tmp_path / "link"
        path.symlink_to(target)
    elif kind == "writable":
        target.chmod(0o666)
        path = target
    elif kind == "foreign-owner":
        path = target
        uid += 1
    elif kind == "parent-symlink":
        parent = tmp_path / "alias"
        parent.symlink_to(tmp_path, target_is_directory=True)
        path = parent / "target"
    else:
        path = Path("relative")
    with pytest.raises((OSError, PermissionError)):
        engine.open_user_path(str(path), uid)


def test_native_spawn_drops_identity_and_reuses_user_xdg(tmp_path, monkeypatch):
    binary, payload = fake_engine(tmp_path, monkeypatch)
    active = tmp_path / "user.config"
    active.write_bytes(b"not parsed as root")
    active.chmod(0o600)
    data = tmp_path / "user-data"
    data.mkdir()
    data.chmod(0o700)
    log = tmp_path / "user.log"
    log.touch(mode=0o600)
    uid, gid = os.getuid(), os.getgid()

    def spawn(command, **kwargs):
        assert kwargs["user"] == uid and kwargs["group"] == gid
        assert kwargs["extra_groups"] == []
        assert kwargs["env"]["HOME"] == supervisor.pwd.getpwuid(uid).pw_dir
        assert command[0].startswith("/proc/self/fd/")
        fd = kwargs["pass_fds"][0]
        assert os.read(fd, len(payload)) == payload
        assert command[command.index("-config") + 1] == str(active)
        assert command[command.index("-dataRootDirectory") + 1] == str(data)
        assert "-tunDevice" in command and "-tunBindInterface" in command
        assert os.fstat(kwargs["stdout"]).st_uid == uid
        return Mock()

    monkeypatch.setattr(supervisor.subprocess, "Popen", spawn)
    supervisor.start_native(
        {
            "op": "start",
            "binary": str(binary),
            "config": str(active),
            "data": str(data),
            "log": str(log),
        },
        "eth0",
        uid,
        gid,
    )
    assert log.stat().st_uid == uid


def test_native_start_rejects_arbitrary_command_fields():
    with pytest.raises(ValueError, match="Unexpected native start fields"):
        supervisor.start_native(
            {"op": "start", "command": ["anything"]}, "eth0", os.getuid(), os.getgid()
        )


def test_privileged_rpc_rejects_generic_apply(monkeypatch):
    replies = []
    monkeypatch.setattr(
        supervisor, "caller_identity", lambda: (os.getuid(), os.getgid())
    )
    monkeypatch.setattr(supervisor.signal, "signal", lambda *args: None)
    monkeypatch.setattr(supervisor, "require_protocol_pipe", lambda: None)
    monkeypatch.setattr(
        supervisor.sys,
        "stdin",
        io.StringIO(
            json.dumps({"op": "apply", "command": ["forbidden"], "undo": []})
            + '\n{"op":"close"}\n'
        ),
    )
    monkeypatch.setattr(supervisor, "respond", replies.append)
    command = Mock(side_effect=AssertionError("No command may execute"))
    monkeypatch.setattr(supervisor, "run", command)
    assert supervisor.worker(native=True) == 0
    assert "Unknown supervisor operation" in replies[0]["error"]
    command.assert_not_called()


def test_protocol_pipe_is_required_before_any_native_mutation(tmp_path, monkeypatch):
    path = tmp_path / "not-a-pipe"
    path.write_text("input")
    with path.open() as stream:
        monkeypatch.setattr(supervisor.sys, "stdin", stream)
        with pytest.raises(RuntimeError, match="protocol pipe"):
            supervisor.worker(native=True)


def test_tun_is_assigned_to_caller_not_supervisor(monkeypatch):
    monkeypatch.setattr(Path, "read_text", lambda path: "1")
    monkeypatch.setattr(routing, "run", lambda command: "")
    owner = Mock()
    routing.configure(owner, "eth0", uid=12345)
    assert owner.apply.call_args_list[0].args[0][-2:] == ["user", "12345"]


def test_binding_probe_does_not_connect_or_send(monkeypatch):
    sock = Mock()
    wrapper = Mock(__enter__=Mock(return_value=sock), __exit__=Mock(return_value=False))
    monkeypatch.setattr(routing.socket, "socket", lambda *a: wrapper)
    routing.check_user_binding("eth0")
    sock.setsockopt.assert_called_once()
    sock.connect.assert_not_called()
    sock.send.assert_not_called()


def test_old_kernel_binding_failure_has_no_root_engine_fallback(monkeypatch):
    sock = Mock()
    sock.setsockopt.side_effect = PermissionError("old kernel")
    monkeypatch.setattr(
        routing.socket,
        "socket",
        lambda *a: Mock(
            __enter__=Mock(return_value=sock), __exit__=Mock(return_value=False)
        ),
    )
    with pytest.raises(RuntimeError, match="refusing a root engine fallback"):
        routing.check_user_binding("eth0")


def test_exact_host_dns_policy_is_reported_without_mutation(monkeypatch):
    policy = "Global: tail2527bd.ts.net ~ts.net\nLink 2 (wlp0s20f3): eleves.polytechnique.fr\nLink 3 (tailscale0): tail2527bd.ts.net eleves.polytechnique.fr ~.\n"
    monkeypatch.setattr(routing.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(Path, "exists", lambda path: True)
    monkeypatch.setattr(
        Path, "resolve", lambda path: Path("/run/systemd/resolve/stub-resolv.conf")
    )
    read = Mock(return_value=policy)
    monkeypatch.setattr(routing, "run", read)
    with pytest.raises((TypeError, KeyError, ValueError)):
        routing.preflight()
    assert all(call.args[0][0] == "ip" for call in read.call_args_list)
