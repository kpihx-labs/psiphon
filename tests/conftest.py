"""Offline tests cannot silently reach an external HTTP endpoint."""

import subprocess
from pathlib import Path

import pytest
import requests


@pytest.fixture(autouse=True)
def no_external_http(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("Offline test attempted a real HTTP request")

    monkeypatch.setattr(requests.Session, "send", refuse)


@pytest.fixture(autouse=True)
def no_privileged_or_host_network_commands(monkeypatch):
    original = subprocess.Popen

    def guarded(command, *args, **kwargs):
        executable = (
            command[0] if isinstance(command, (list, tuple)) else command.split()[0]
        )
        if Path(executable).name in {"sudo", "ip", "sysctl", "resolvectl"}:
            raise AssertionError(
                f"Offline test attempted a real system command: {executable}"
            )
        return original(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", guarded)
