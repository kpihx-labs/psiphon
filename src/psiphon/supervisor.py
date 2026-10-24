"""Pipe-owned engine and network transaction. EOF rolls back even after SIGKILL.

The worker alone performs mutations, records successful inverse operations, and
owns the engine. Native mode elevates this trusted local installation via sudo,
not the controller. Its RPC is fixed-purpose; it is not a security boundary
against modification of the installed Python interpreter/package being approved.
"""

import json
import os
import pwd
import shutil
import signal
import stat
import subprocess
import sys
from pathlib import Path
from types import TracebackType
from typing import Any, Self


class RollbackError(RuntimeError):
    """Cleanup was incomplete: no subsequent session may be attempted silently."""


def respond(reply: dict) -> None:
    # Unbuffered writes avoid interpreter flush errors after controller SIGKILL.
    data = memoryview((json.dumps(reply) + "\n").encode())
    while data:
        count = os.write(sys.stdout.fileno(), data)
        data = data[count:]


def run(command: list[str]) -> str:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        start_new_session=True,
    )
    if result.returncode:
        raise RuntimeError(f"{' '.join(command)}: {result.stderr.strip()}")
    return result.stdout


class Transaction:
    def __init__(self) -> None:
        self.undo: list[list[str]] = []

    def apply(self, command: list[str], undo: list[str]) -> None:
        try:
            run(command)
        except subprocess.TimeoutExpired:
            # An interrupted command may already have mutated the kernel.
            self.undo.append(undo)
            raise
        self.undo.append(undo)

    def close(self) -> list[str]:
        errors = []
        for command in reversed(self.undo):
            try:
                run(command)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                errors.append(str(exc))
        self.undo.clear()
        return errors


def stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def ignore_terminal_signal(signum, frame) -> None:
    # A caught handler resets to default across exec, unlike SIG_IGN. This avoids
    # preexec_fn and gives the engine normal signals without a privileged window.
    pass


def caller_identity() -> tuple[int, int]:
    if os.geteuid() != 0:
        raise PermissionError("Native network supervisor was not elevated")
    uid = int(os.environ.get("SUDO_UID", str(os.getuid())))
    if uid < 0:
        raise PermissionError("Invalid sudo caller UID")
    return uid, pwd.getpwuid(uid).pw_gid


def require_protocol_pipe() -> None:
    if not stat.S_ISFIFO(os.fstat(sys.stdin.fileno()).st_mode):
        raise RuntimeError(
            "Elevation policy did not preserve the stdin protocol pipe; no network changes are allowed"
        )


def start_native(request: dict, uplink: str, uid: int, gid: int) -> subprocess.Popen:
    from psiphon import config, engine

    if set(request) != {"op", "binary", "config", "data", "log"}:
        raise ValueError("Unexpected native start fields")
    # These paths are only consumed by the dropped-privilege engine. Root never
    # loads the caller's core configuration or creates files in the caller's XDG.
    for key, flags in (("config", os.O_RDONLY), ("data", os.O_RDONLY | os.O_DIRECTORY)):
        fd = engine.open_user_path(request[key], uid, flags)
        os.close(fd)
    snapshot = engine.sealed_engine(request["binary"], uid)
    try:
        log_fd = engine.open_user_path(request["log"], uid, os.O_WRONLY | os.O_APPEND)
        try:
            command = [
                f"/proc/self/fd/{snapshot}",
                "-config",
                request["config"],
                "-dataRootDirectory",
                request["data"],
                "-tunDevice",
                config.TUN_NAME,
                "-tunBindInterface",
                uplink,
                "-tunDNSServers",
                config.BYPASS_DNS,
            ]
            account = pwd.getpwuid(uid)
            return subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                pass_fds=(snapshot,),
                start_new_session=True,
                user=uid,
                group=gid,
                extra_groups=[],
                env={
                    "PATH": "/usr/bin:/bin",
                    "HOME": account.pw_dir,
                    "USER": account.pw_name,
                    "LOGNAME": account.pw_name,
                    "LANG": "C.UTF-8",
                },
            )
        finally:
            os.close(log_fd)
    finally:
        os.close(snapshot)


def worker(native: bool = False) -> int:
    # sudo retains the caller's tty for its credential ticket. Only the controller
    # handles terminal signals; EOF owns cleanup. Engine dispositions are reset.
    if native:
        require_protocol_pipe()
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT):
            signal.signal(signum, ignore_terminal_signal)
    uid, gid = caller_identity() if native else (os.getuid(), os.getgid())
    transaction = Transaction()
    process = None
    uplink = None
    errors = []
    try:
        for line in sys.stdin:
            request = json.loads(line)
            if request["op"] == "close":
                break
            try:
                result: Any = None
                if request["op"] == "configure" and native:
                    from psiphon import routing

                    if uplink is not None:
                        raise RuntimeError("Network already configured")
                    selected = routing.preflight(request.get("interface"))
                    routing.configure(transaction, selected, uid)
                    uplink = selected
                    result = uplink
                elif request["op"] == "apply" and not native:
                    transaction.apply(request["command"], request["undo"])
                elif request["op"] == "start":
                    if process is not None:
                        raise RuntimeError("Engine already started")
                    if native:
                        if not uplink:
                            raise RuntimeError("Native network is not configured")
                        process = start_native(request, uplink, uid, gid)
                    else:
                        with open(request["log"], "ab") as log:
                            process = subprocess.Popen(
                                request["command"],
                                stdin=subprocess.DEVNULL,
                                stdout=log,
                                stderr=subprocess.STDOUT,
                                start_new_session=True,
                            )
                    result = process.pid
                elif request["op"] == "poll":
                    result = process.poll() if process else None
                else:
                    raise RuntimeError("Unknown supervisor operation")
                respond({"result": result})
            except (
                OSError,
                RuntimeError,
                ValueError,
                KeyError,
                subprocess.TimeoutExpired,
            ) as exc:
                respond({"error": str(exc)})
    except BrokenPipeError:
        pass  # Controller died while a reply was in flight; cleanup still runs.
    finally:
        try:
            stop(process)
        finally:
            errors = transaction.close()
            for error in errors:
                print(f"ROLLBACK FAILED: {error}", file=sys.stderr, flush=True)
    return int(bool(errors))


class Supervisor:
    def __init__(self, native: bool = False) -> None:
        command = [sys.executable, "-m", "psiphon.supervisor"]
        if native:
            # -I ignores ambient PYTHONPATH/user-site. The explicitly selected
            # interpreter and package are still a trusted local installation,
            # possibly editable and user-writable, NOT an isolated root helper.
            root = str(Path(__file__).resolve().parent.parent)
            code = f"import sys; sys.path.insert(0, {root!r}); from psiphon.supervisor import worker; raise SystemExit(worker(native=True))"
            command = [sys.executable, "-I", "-c", code]
            if os.geteuid() != 0:
                sudo = shutil.which("sudo")
                if not sudo:
                    raise RuntimeError(
                        "Native networking needs sudo; proxy mode does not"
                    )
                # Authenticate against the terminal, NEVER against the JSON pipe.
                subprocess.run([sudo, "-v"], check=True)
                command = [sudo, "-n", "--", *command]
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            start_new_session=not native,
        )

    def request(self, op: str, **kwargs: Any) -> Any:
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(json.dumps({"op": op, **kwargs}) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(
                "Supervisor exited unexpectedly; inspect rollback output"
            )
        reply = json.loads(line)
        if "error" in reply:
            raise RuntimeError(reply["error"])
        return reply.get("result")

    def apply(self, command: list[str], undo: list[str]) -> None:
        self.request("apply", command=command, undo=undo)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        typ: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        assert self.process.stdin is not None and self.process.stdout is not None
        try:
            self.process.stdin.close()  # EOF: stop engine first, then undo in reverse order.
        except BrokenPipeError:
            pass  # Authentication/worker failure already closed the other end.
        reply = self.process.stdout.read()
        code = self.process.wait()
        self.process.stdout.close()
        if code:
            raise RollbackError(f"Supervisor rollback failed (exit {code}): {reply}")


if __name__ == "__main__":
    raise SystemExit(worker())
