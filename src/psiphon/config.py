"""psiphon configuration constants (single source of truth).

Plain constants only, no loader, no YAML (k-project standard).
Resources ship inside the package; runtime files use Linux XDG locations.
"""

import os
from pathlib import Path

# Project tree
RESOURCES = Path(__file__).resolve().parent / "assets"
BASE_CONFIG = RESOURCES / "psiphon.config"
ENGINE_LICENSE = RESOURCES / "LICENSE.engine"
ENGINE_REVISION = "33ff79e89260f3adf92e846b96b3369b86a819d8"
SOURCE_REVISION = "c4a09096ab401b57f52e092c8f2f829c8fac7628"
ENGINE_URL = (
    "https://raw.githubusercontent.com/Psiphon-Labs/"
    f"psiphon-tunnel-core-binaries/{ENGINE_REVISION}/linux/psiphon-tunnel-core-x86_64"
)
ENGINE_SHA256 = "046ca168da25d2c0e61c1c15e2b73bfbb67f5208112a4c94fe58fc5aab784f19"
ENGINE_LICENSE_SHA256 = (
    "0ae0485a5bd37a63e63603596417e4eb0e653334fa6c7f932ca3a0e85d4af227"
)
ENGINE_MAX_BYTES = 64 * 1024 * 1024


def _xdg(name: str, fallback: str) -> Path:
    value = os.environ.get(name, "")
    base = (
        Path(value) if value and Path(value).is_absolute() else Path.home() / fallback
    )
    if base.resolve() == Path.home().resolve():
        base = Path.home() / fallback
    return base


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "psiphon"
STATE_DIR = _xdg("XDG_STATE_HOME", ".local/state") / "psiphon"
CACHE_DIR = _xdg("XDG_CACHE_HOME", ".cache") / "psiphon"
ENGINE_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "psiphon" / ENGINE_REVISION
BINARY = ENGINE_DIR / "psiphon-tunnel-core-x86_64"
_runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
if (
    not _runtime.is_absolute()
    or not _runtime.is_dir()
    or _runtime.resolve() == Path.home().resolve()
):
    _runtime = Path("/tmp")
RUNTIME_DIR = _runtime / f"psiphon-{os.getuid()}"
ACTIVE_CONFIG = CONFIG_DIR / "psiphon.config"
PID_FILE = RUNTIME_DIR / "psiphon.pid"
LOG_FILE = STATE_DIR / "psiphon.log"
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUPS = 4
SESSION_FILE = RUNTIME_DIR / "session.json"
DATA_DIR = CACHE_DIR / "core"  # signed server-list cache and tunnel-core datastore

# Local proxy endpoints exposed by tunnel-core.
# Deliberately NOT 8081/1081 (the community defaults): 8081 is taken on
# kpihx-ubuntu by the SearXNG container (docker-proxy, root-owned) and stealing
# it would break the metasearch stack. 18081/11081 verified free (2026-10-23).
PROXY_HOST = "127.0.0.1"
HTTP_PROXY_PORT = 18081
SOCKS_PROXY_PORT = 11081

# Isolated policy routing resources. Refuse occupied tables/priorities/interfaces.
TUN_NAME = "psiphon0"
TUN_ADDRESS = "172.31.255.1/32"
TUN_MTU = 1500
TRANSPARENT_DNS = "10.0.0.2"
BYPASS_DNS = "8.8.8.8,8.8.4.4"
ROUTE_TABLE = "18081"
BYPASS_PRIORITY = "100"
TUN_PRIORITY = "101"
ROUTE_PROBE_IP = "1.1.1.1"

# Measurement
SPEEDTEST_URL = "https://speed.cloudflare.com/__down?bytes=40000000"
UPLOAD_URL = "https://speed.cloudflare.com/__up"
GEO_URL = "https://ipwho.is/"
IP_URLS = ("https://api.ipify.org", "https://ifconfig.me/ip")
CONNECT_WAIT_S = 45  # bounded wait for a real tunnel and HTTPS, not just sockets
BENCH_DEFAULT_S = 6  # default speed-test duration

# Psiphon documented egress regions (community-documented set; any ISO code is
# accepted, but availability depends on Psiphon's live server fleet).
REGIONS = {
    "AU": "Australia",
    "AT": "Austria",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "CA": "Canada",
    "CH": "Switzerland",
    "CZ": "Czechia",
    "DE": "Germany",
    "DK": "Denmark",
    "EE": "Estonia",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GB": "United Kingdom",
    "HU": "Hungary",
    "IE": "Ireland",
    "IN": "India",
    "ID": "Indonesia",
    "IT": "Italy",
    "JP": "Japan",
    "LV": "Latvia",
    "LT": "Lithuania",
    "NL": "Netherlands",
    "NO": "Norway",
    "PL": "Poland",
    "RO": "Romania",
    "RS": "Serbia",
    "SE": "Sweden",
    "SG": "Singapore",
    "SK": "Slovakia",
    "US": "United States",
}

DEBUG = False
