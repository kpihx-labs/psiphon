# CONTRACT

This document is the non-negotiable source of truth for the project contract.
The v2 section below supersedes the preserved historical v1 sections.

If implementation, wrappers, or docs conflict with this contract, this contract wins.

---

## 1) Metadata

- `schema_version`: `psiphon.contract.v1`
- `contract_version`: `1.0.0`

Keep the same metadata in `pyproject.toml` under a dedicated tool/config section.

---

## 2) Conventions

- CLI commands are lowercase verbs: `regions`, `connect`, `status`, `ip`, `speed`,
  `disconnect`, `service`.
- Times: seconds as float (`*_s` naming in code, `--seconds` on CLI).
- Region codes: ISO 3166-1 alpha-2, uppercased before use.
- State files: fixed names under `~/.psiphon/` (`psiphon.config`, `psiphon.pid`,
  `psiphon.log`, `data/`).

---

## 3) Shared types

- `EgressRegion`: `str` ISO code (e.g. `"JP"`).
- `TunnelState`: `{running: bool, pid: int | None, region: str | None,
  http_port: int, socks_port: int}`.
- `SpeedMeasurement`: `{mbps: float, bytes: int, elapsed_s: float, region: str | None}`.

---

## 4) Error model

| Code / situation | Meaning |
|---|---|
| exit 1 + `Binary missing` | tunnel-core binary absent (fetch command shown) |
| exit 1 + `CONNECTION FAILED` | process died or proxy ports never opened (log tail shown) |
| exit 1 + `Tunnel is not running` | `speed`/`ip` called without an active tunnel |
| exit 2 | invalid `service` action |
| Python exception boundary | unexpected failure — must fail loud, never silent |

---

## 5) Internal API

| Operation | Input | Output |
|---|---|---|
| `connect` | `region: str` (req), `foreground: bool` | success panel (ports, pid) or exit 1 + log tail |
| `disconnect` | - | confirmation (pid killed) or "not running" |
| `status` | - | table: tunnel/PID/region/ports/log |
| `regions` | - | table of known regions + active marker |
| `ip` | - | table: direct IP vs tunnel egress IP |
| `speed` | `seconds: float = 6` | panel: real Mbps through tunnel |
| `service install` | `region: str = DE` | systemd user unit installed + started |
| `service uninstall` / `status` | - | unit removed / active state |

---

## 6) Transport mappings

- Single transport: local CLI (typer). Every command maps 1:1 to the internal API
  above. No MCP/HTTP surface in v1.

---

## 7) Compliance rules

- Wrappers must not alter business semantics.
- Wrappers must not remap canonical error codes.
- Any breaking change requires `schema_version` major bump (`psiphon.contract.v2`).
- The tunnel binary is third-party (Psiphon-Labs): never fork it, only wrap it.

## v1.1 operational clarifications (2026-10-23, supersedes conflicting older rows)

- `connect` success requires an actual tunnel and a verified HTTPS public IP.
  A listening proxy is insufficient. A different reported region fails rather
  than silently changing the requested location.
- `speed` validates HTTPS through the explicit proxy and measures received bytes
  over actual elapsed time, including setup; errors never become zero-Mbps claims.
- `service uninstall` stops/disables the unit but preserves its kernel symlink.
- Default proxy ports are HTTP 18081 and SOCKS 11081. Proxy mode does not claim
  device-wide coverage, leak prevention, UDP protection or guaranteed anonymity.

## v1.2 repository ownership (supersedes the v1.1 kernel-symlink note)

- Service configuration is rendered from this repository's assets/psiphon.service.
  No agents registry or skill is required. Uninstall removes the generated unit;
  unrelated or symlinked unit files are not overwritten.
- Configuration uses XDG config, datastore/cache uses XDG cache, logs use XDG state,
  and PID/session data uses XDG runtime or Linux /tmp. No home-root state is created.
- A fresh matching ConnectedServerRegion notice and active tunnel are required
  before HTTPS readiness can succeed. The catalogue is not an availability promise.
- Offline quality gates never invoke the live survey. The explicit opt-in test
  records all announced/catalogue country attempts, measurements and errors.

## v2 foreground native contract (2026-10-24)

- `schema_version`: `psiphon.contract.v2`; `contract_version`: `2.0.0`.
- Commands: `setup`, `doctor`, `connect`, `disconnect`, `regions`, `status`, `bench`.
  Service management is removed; status replaces the old IP/speed commands.
- Every public option has a short alias. `-h/--help`, `-v/--version` are available.
- Connect stays foreground. Native TUN is default; `-p/--proxy` explicitly selects
  loopback HTTP/SOCKS and performs no route/DNS mutations. Normal native connect
  requests sudo for its network supervisor only, after read-only preflight.
- Setup uses a pinned official URL and SHA-256; installs into XDG data atomically.
  Base config and exact separate upstream GPL text ship inside the Python package.
  The BUSL license covers only the independent wrapper.
- Doctor is offline/read-only: engine integrity and selected-mode prerequisites,
  not a claim of packet-capable exits or successful network connectivity.
- Native controller/setup remain unprivileged and reuse the caller's XDG state.
  Only the network supervisor runs elevated; the verified engine drops to the
  caller UID/GID with an owned TUN and no supplementary groups. No root shell/setup.
- Native mode requires sudo for network mutations, the resolved stub and no
  conflicting owned routes/rules/TUN. It uses native ConsoleClient flags, not
  tun2socks. Only temporary dedicated policy resources and per-link DNS/sysctls
  change; no permanent routes, global sysctls, resolver-file edits or services.
- Native readiness: fresh tunnel + matching requested region + established packet
  channel + active owned IPv4 TUN route + valid HTTPS public IP. IPv6 is blocked
  for nonlocal traffic during the session. Packet-unsupported regions fail bounded
  readiness instead of falling back to proxy mode.
- A pipe-owned supervisor stops/reaps the engine and reverses successful mutations
  after normal exit, startup failure, SIGTERM, Ctrl-C or controller SIGKILL. Cleanup
  errors must surface. Killing the supervisor/host or concurrent administrator/DNS
  changes are outside this guarantee. Uplink-bound sockets can bypass the TUN;
  this is not an application isolation boundary or permanent kill switch.
- Status defaults to the current OS route plus HTTPS IP, independent of any saved
  session. Proxy, GeoIP, download and upload are explicit flags. No automatic sweep.
- Bench requires `--all/-a` or repeated `--region/-r`; all scope includes catalogue
  and observed fleet codes and extends on new notices. Record per-attempt failures
  and exact coverage in private XDG cache JSONL. Failed transfers are never zero.
- XDG config/cache/state/runtime separate preferences, datastore, logs and volatile
  controller identity. Old historical home-root/service paths above are not used.
- Exit 2: invalid options/region/scope. Exit 1: setup, preflight, readiness,
  measurement or cleanup failure. Bench records country-level failures and continues
  coverage; this is not proof every region works. Unexpected engine exit is failure.
- Offline `make check` includes build and installed-wheel validation, never setup,
  live benchmark, root networking, publishing, pushing or global installation.
- Sudo authenticates against the terminal, never the stdin JSON pipe. The elevated
  worker permits only fixed native operations and independently verifies the
  engine's pinned hash and caller-owned non-symlink path before exec of a sealed
  snapshot. User configuration is not parsed as root; user state is not created as
  root. The local interpreter/package, potentially editable, are explicitly trusted
  by the sudo approval; they are not a tamper-resistant privileged boundary.
- Existing per-link DNS domains are saved, temporarily cleared to make tunnel
  DNS exclusive for public names, and restored exactly. Global domains remain
  configured but their resolver packets follow tunnel policy; private campus or
  Tailscale names may be unavailable during the connection. Persistent resolver
  configuration is never edited. Native coverage and rechecks are in BENCHMARKS.md.

### 2.0.3 connected bridge routing amendment

- At connection time, discover actual Linux bridges and their directly connected
  scope-link IPv4 routes in main. Copy only nondefault unicast prefixes without
  gateways into the owned VPN table. Do not copy physical uplink routes or exempt
  entire RFC1918 ranges.
- Every copied route has an inverse transaction entry. Main routes, bridge MACs
  and port membership remain untouched. Bridges created mid-session require
  reconnect; no permanent network watcher is installed.
- Existing IPv6 blocking and Internet TUN policy remain unchanged. This local IPC
  fix does not promise compatibility with arbitrary third-party kill switches.
