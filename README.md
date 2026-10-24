# psiphon

Independent Linux x86-64 CLI around the unchanged official Psiphon ConsoleClient.
Version 2 runs in the foreground: native packet tunnel by default, explicit local
HTTP/SOCKS proxy with `--proxy/-p`. Native connect automatically requests sudo
for its network supervisor only. No systemd service or root shell is required.

## Install and setup

```bash
sudo apt install iproute2 systemd-resolved curl sudo
uv tool install psiphon
psiphon setup               # explicit network download, no route changes
psiphon doctor              # offline engine/hash and native prerequisite checks
```

First-time dependency retrieval can use `uv sync` explicitly. `make uv-link` is
available for editable development. No engine is bundled in the wheel. Setup
downloads only the pinned official artifact, checks SHA-256 before installation,
then atomically installs it in `$XDG_DATA_HOME/psiphon/<revision>/` (default
`$HOME/.local/share`). A valid existing engine requires no download. Failed hashes
leave the existing binary untouched. Only Linux x86-64 is supported by this pin.

The artifact repository revision is
`33ff79e89260f3adf92e846b96b3369b86a819d8`, with SHA-256
`046ca168da25d2c0e61c1c15e2b73bfbb67f5208112a4c94fe58fc5aab784f19`.
Its official commit describes source revision `c4a09096ab401b57f52e092c8f2f829c8fac7628`.
That metadata is provenance, not a reproducible-build or signed-release guarantee.
The pin and URLs live in `src/psiphon/config.py`; no moving-master downloads occur.

## Foreground use

```bash
# No root and no OS route/DNS changes. Leave this terminal running:
psiphon connect -p -r FR
# In another terminal, explicitly measure the local proxy:
psiphon status -p -g --speed -n 3
curl --proxy socks5h://127.0.0.1:11081 https://api.ipify.org

# Native mode, from your normal shell, using the SAME user setup and XDG state:
psiphon doctor                     # read-only; does not ask sudo
psiphon connect -r DE              # requests sudo automatically if preflight passes
# Optional -i eth0 selects the bypass interface.
```

Setup, doctor, controller, configuration, logs and datastore remain under your
normal user. There is no root setup or root XDG copy. After read-only preflight,
connect authenticates with `sudo -v` at the terminal, then launches only the network
supervisor through noninteractive sudo. Password input is never read from the
controller/supervisor JSON pipe. If elevation policy replaces that pipe with a TTY,
the worker refuses before mutations. Cancellation starts no supervisor or route change.
For agent-operated privilege, launch connect only in an armed tmux pane in the
agent's current window. No sudo or privileged operation runs in offline checks.

**Escalation trust:** sudo approves this local Python interpreter and installed
package, including an editable checkout if that is what you installed. They may
be user-writable. `-I` avoids ambient PYTHONPATH/user-site, but does not make that
code, its environment or its dependencies a tamper-resistant root helper. This is
trusted local-install escalation, equivalent in trust to running a local script
through sudo, not a boundary against a compromised account/installation. Prefer a
reviewed wheel installation; do not add a passwordless sudoers rule for the helper.

The elevated worker accepts fixed native operations, not arbitrary command arrays.
It independently checks engine ownership, path components and the pinned SHA-256,
then executes a sealed memfd snapshot, preventing executable replacement after the
hash check. Symlinked engine paths and group/world-writable engine paths/ancestors
are refused. A local libc memfd API is used if the Python build omits its wrapper.
The TUN is assigned to the caller UID. The engine runs with the caller UID/GID,
no supplementary groups, and only its verified descriptor inherited besides
standard I/O; it reads the
user configuration and writes the user datastore. Root does not parse the user's
engine configuration or create root-owned XDG state. Modern Linux permits an
initial unprivileged SO_BINDTODEVICE; a local socket-only preflight rejects hosts
where this fails. There is no fallback to a root engine.

Region selection is optional: without `-r`, the engine chooses. A requested region
must match its fresh reported region before readiness succeeds. Ctrl-C stops the
session and rolls back. `disconnect` requests termination of the owned controller
in the same user/XDG context; it checks PID start time and exact command identity.
There is no detached mode. HTTP is `127.0.0.1:18081`, SOCKS is `127.0.0.1:11081`.
Busy ports are not stolen. Native mode disables both local proxies.

## Native routing and limits

ConsoleClient opens a **preexisting named TUN** using `-tunDevice`, binds its
transport sockets to the uplink with `-tunBindInterface`, and uses
`-tunDNSServers` for bypass/bootstrap DNS. The wrapper does not use tun2socks.

The session supervisor creates only its own TUN, policy table and rules:

- IPv4 routes through `psiphon0` in table 18081, priority 101. Priority 100 permits
  explicitly uplink-bound IPv4 sockets to use the unchanged main table. This is
  the engine's escape path, not an application-isolation/security boundary.
- Local-address routing remains local. Other IPv4 traffic, including LAN traffic,
  goes to the TUN. IPv6 nonlocal traffic is temporarily unreachable; this wrapper
  does not claim tested native IPv6 support. No global IPv6/sysctl switch changes.
- Reverse-path filtering changes to loose mode only on the uplink and owned TUN;
  previous per-link values are restored. Existing main routes remain untouched.
- DNS uses upstream's transparent IPv4 resolver **10.0.0.2**, with `resolvectl dns`
  and routing domain `~.` on the owned link. Upstream also defines transparent
  IPv6 DNS `fd19:ca83:e6d5:1c44::2`, unused by this IPv4-only policy.
- Native preflight requires the systemd-resolved stub, free session resources
  and compatible policy rules. Per-link DNS domains are saved, temporarily cleared
  and restored exactly. Global domains remain configured; their resolver traffic
  also follows the TUN. Private campus/Tailscale names can be unavailable during
  the session. No persistent DNS configuration or resolv.conf is rewritten.

The native survey on 2026-10-24 exercised 31 codes on the workstation with
Tailscale/campus DNS present. Sixteen produced verified packet-tunnel downloads;
all sessions restored the original routes and per-link DNS domains. See
`BENCHMARKS.md` for failures and qualifications.

Each successful mutation has an inverse. The supervisor owns the engine and
observes a private pipe: normal exit, startup failure, SIGTERM, Ctrl-C or controller
SIGKILL closes it, stops/reaps the engine, and rolls back in reverse order. Cleanup
errors are explicit, never ignored. This is not protection against the supervisor
itself being killed, host failure, an administrator changing resources mid-session,
new DNS configuration appearing mid-session, or applications deliberately binding
to the bypass interface. It is not a permanent kill switch. Ordinary connectivity
returns after rollback. Do not use this as an anonymity or comprehensive leak-proof
security boundary. The live validation is scoped to the tested host and fleet.

Not every proxy exit supports the packet-tunnel SSH channel. Native readiness
requires a fresh tunnel notice, matching region, the channel-established diagnostic,
the active TUN route, and a real HTTPS public-IP response over that route. A proxy
success is never substituted. Missing packet support times out and rolls back;
the engine selects/retries its servers. The wait budget bounds readiness polling,
not OS hostname-resolution stalls. Availability and traffic rules remain fleet-controlled.

Official source references, at the pinned source revision:

- [ConsoleClient flags and device binding](https://github.com/Psiphon-Labs/psiphon-tunnel-core/blob/c4a09096ab401b57f52e092c8f2f829c8fac7628/ConsoleClient/main.go)
- [Transparent DNS and packet rewriting](https://github.com/Psiphon-Labs/psiphon-tunnel-core/blob/c4a09096ab401b57f52e092c8f2f829c8fac7628/psiphon/common/tun/tun.go)
- [Packet SSH channel establishment](https://github.com/Psiphon-Labs/psiphon-tunnel-core/blob/c4a09096ab401b57f52e092c8f2f829c8fac7628/psiphon/tunnel.go)

## Status and explicit benchmarks

```bash
psiphon status                   # current OS route + HTTPS IP, with or without Psiphon
psiphon status -g                 # opt-in third-party country/city lookup
psiphon status --speed -n 3       # explicit download and upload on the current route
psiphon status -p -g -d           # explicit local proxy instead
psiphon regions                  # catalogue + last observed fleet notice
psiphon bench -r FR -r JP -p      # selected proxy regions, no OS route changes
psiphon bench -a -p               # explicit all-region proxy survey
psiphon bench -a                  # explicit native survey; sudo supervisor per session
```

All custom CLI options have short aliases; help is `-h/--help`, version is `-v`.
Status does not depend on a saved Psiphon PID and never silently chooses the proxy.
Ambient proxy and NO_PROXY settings are ignored. GeoIP is a database observation,
not proof of physical location; opting in discloses the measured IP to ipwho.is.
IP queries and speed tests also contact external services.

Downloads stream real payload. Uploads stream at most 40 MB per sample and require
a successful HTTP response, not just locally queued bytes. Timing includes setup
and response overhead; `-s` is a measurement/send budget, not an absolute deadline.
Errors remain errors, never zero-Mbps results. Endpoints live in `config.py`.

`bench` requires either `-a` or repeated `-r`. All-region scope is the catalogue
union observed fleet codes, extended when later notices announce additional codes;
it is not a claim to discover every server or every future region. Each region is
attempted once. Private JSONL records errors and measurements, then exact selected
and attempted sets. It does not run from ordinary connect/status or offline checks.
Historical proxy measurements remain in [BENCHMARKS.md](BENCHMARKS.md); they do not
validate the new native path. No standalone benchmark scripts are used.

## State, packaging and development

| Data | Default location |
|---|---|
| Packaged defaults and verbatim engine license | `src/psiphon/assets/` (also in wheel) |
| Verified engine and its separate GPL license | `$XDG_DATA_HOME/psiphon/<revision>/` |
| Active engine configuration | `$XDG_CONFIG_HOME/psiphon/psiphon.config` |
| Engine server lists/datastore | `$XDG_CACHE_HOME/psiphon/core/` |
| Explicit benchmark observations | `$XDG_CACHE_HOME/psiphon/bench-<UTC>.jsonl` |
| Append-only diagnostic log | `$XDG_STATE_HOME/psiphon/psiphon.log` |
| Controller lock and identity | `$XDG_RUNTIME_DIR/psiphon-<uid>/`, or `/tmp/psiphon-<uid>/` |

Standard XDG fallbacks apply. Directories and runtime files are private. Logs and
benchmarks can contain IPs and diagnostic URLs; do not publish them raw. No account
or password is stored. Old service assets and management code are removed; upgrading
does not stop or remove a previously installed OS service automatically. Such a unit
must be explicitly stopped/disabled before migration; this offline pass does not
change the installed system or global tool.

`make check` synchronizes from the frozen lock **offline**, builds the wheel,
runs Ruff, compilation, Pyright, offline behavior/failure-injection tests and an
isolated installed-wheel resource/CLI test. Real pipe EOF/SIGKILL tests use dummy
processes and temporary files, never a VPN or privileged route command.

`make build` builds locally. `make publish` is an explicit remote action and must
run in an approved `with-env` tmux pane. `make push` uses the current branch and
both SSH remotes `github` and `gitlab`, failing on errors. Neither is run by checks.

## License and trust

Only the original Python wrapper is BUSL 1.1, with the personal/noncommercial
academic grant in [LICENSE](LICENSE), changing to AGPL-3.0-only no later than
2030-10-24. Its legal body is canonical and does not relicense the engine.

The external engine remains upstream GPLv3 (source notices specify version 3 or
later). The exact pinned upstream license is shipped separately at
`src/psiphon/assets/LICENSE.engine` and copied beside the engine by setup. The wheel
contains no engine binary. Anyone redistributing the engine must separately meet
upstream GPL and corresponding-source obligations; the wrapper license grants no
rights to Psiphon's trademarks or service. Psiphon operates the exit fleet, not
this wrapper. Neither universal DPI evasion nor anonymity is guaranteed.
