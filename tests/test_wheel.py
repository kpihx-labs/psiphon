"""Test the built wheel as installed files, without source-checkout resources."""

import json
import subprocess
import sys
import tomllib
from pathlib import Path


def test_installed_wheel_resources_and_cli(tmp_path):
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text())
    version = metadata["project"]["version"]
    wheel = root / "dist" / f"psiphon-{version}-py3-none-any.whl"
    assert wheel.exists(), "Run make check (builds the wheel offline first)"
    target = tmp_path / "installed"
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--offline",
            "--no-deps",
            "--target",
            str(target),
            str(wheel),
        ],
        check=True,
    )
    script = (
        "import sys,json; sys.path.insert(0,sys.argv[1]); "
        "from psiphon import config, engine; "
        "assert config.BASE_CONFIG.is_file(); "
        "assert engine.digest(config.ENGINE_LICENSE)==config.ENGINE_LICENSE_SHA256; "
        "assert json.loads(config.BASE_CONFIG.read_text())['SponsorId']; "
        "from psiphon.main import app; from typer.testing import CliRunner; "
        "r=CliRunner().invoke(app,['connect','-h']); "
        "assert r.exit_code==0,r.output; print(config.RESOURCES)"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(target)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert str(target) in result.stdout and str(root / "src") not in result.stdout
    assert json.loads((target / "psiphon/assets/psiphon.config").read_text())
