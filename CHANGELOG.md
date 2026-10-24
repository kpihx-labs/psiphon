# Changelog

## [2.0.1] - 2026-10-24

- Add targeted `make purge` and a Rich table/JSON active-route status view.

## Unreleased

## [2.0.0] - 2026-10-24

- Correct native UX: normal-user connect automatically authenticates sudo only
  for the network supervisor, retaining user XDG setup/config/logs/datastore.
- Elevated fixed-purpose RPC verifies a caller-owned engine path and pinned hash,
  executes an immutable sealed snapshot, and drops engine UID/GID/groups. Document
  local-install escalation trust honestly; no claim of a secure editable-code boundary.
- Save and temporarily clear competing per-link DNS domains, restoring them on
  shutdown; preserve global domains and persistent resolver configuration.
- Validate native routing across 31 country codes, then recheck five exits with
  download/upload. Germany reached 125.357/35.770 Mbps; France 125.107/38.407 Mbps.
- Live native check confirmed psiphon0 routing and nonlocal IPv6 rejection.

- Foreground native ConsoleClient packet tunnel by default, explicit proxy mode.
- Remove service management/assets; add pinned XDG engine setup, integrity checks
  and offline doctor. Ship defaults and verbatim upstream GPL inside the package.
- Pipe-owned engine supervisor with inverse network transactions and EOF cleanup,
  including controller SIGKILL. Dedicated policy routes, temporary per-link DNS,
  per-link reverse-path filtering and nonlocal IPv6 blocking; conservative preflight.
- Generic active-route status with opt-in GeoIP/download/upload; explicit region
  benchmark command. All public options have short aliases.
- Restore the missing canonical BUSL legal sentence; upstream GPL stays separate.
- Update offline build/check and explicit publish/push workflows; quality checks
  never start privileged networking or publish packages.

- Apply BUSL 1.1 to the original local wrapper, with the approved personal/
  academic production grant and AGPL-3.0-only Change License on 2030-10-24.
  The unchanged Psiphon tunnel-core binary remains upstream GPLv3.

All notable changes to this project will be documented in this file.

Format: Keep a Changelog. Versioning: SemVer.

## [1.2.0] - 2026-10-24

- Move the editable checkout to VPNs/psiphon and reinstall the moved environment.
- Separate XDG config, cache, persistent logs and volatile PID/session data.
- Move service ownership to the repository template; generate/remove the user
  unit without agents registries, skills or symlinks. Preserve unrelated units.
- Remove the active dedicated kernel skill; k-clis/k-ubuntu only list the clients.
- Require matching reported region as well as a real HTTPS exit for readiness.
- Preserve core preferences, validate process identity and isolate offline tests.
- Reap-state checks distinguish zombies from running processes; stale metadata
  cannot kill an unrelated process or follow a foreign runtime symlink. Foreground
  execution retains its PID for the other control commands.
- Add an explicit all-region integration test, separate from make check; preserve
  measured errors rather than converting them into zero-Mbps results.
- Existing MIT wrapper licensing is retained; the official external engine remains
  GPLv3, unmodified, with its upstream artifact hash independently confirmed.

The older kernel-symlink lifecycle notes below are historical and superseded.

## [1.1.0] - 2026-10-23 - Operational validation follow-up

Verified HTTPS readiness, explicit proxy routing, live region notices, safe PID
handling, CLI/service coordination and tested crash recovery. The original
1.0.0 history and subsequent corrections are preserved below; the package's
current version is 1.1.0.

The final lifecycle check found that systemctl disable also removes external unit
aliases. Stop/disable now restores the registered canonical symlink, reloads the
user manager, and leaves LoadState=loaded, ActiveState=inactive, UnitFileState=linked.
The actual lifecycle and recovery check was repeated after this fix.

## [1.0.0] - 2026-10-23

### Subsequent validation and corrections (v1.1.0, 2026-10-23)

- Installed `psiphon` as an editable user command. Actual ports are 18081/11081;
  the original 8081/1081 entry below is historical and superseded.
- Readiness requires an active tunnel notice plus verified HTTPS/public IP,
  not merely a listening socket. Verify the reported server region.
- Disable ambient proxy inheritance, reject non-IP responses and bound probes.
- Validate process identity before stopping a stored PID; coordinate CLI/service
  modes, detect unit symlink mismatch and surface stop/disable failures.
- Exercise HTTP, SOCKS (remote DNS) and real systemd SIGKILL auto-recovery.
- Preserve measured throughput, errors and limitations in BENCHMARKS.md.

### Added

- Initial release: `psiphon` controller for official `psiphon-tunnel-core`.
- Commands: `regions`, `connect --region`, `disconnect`, `status`, `ip`, `speed`,
  `service install|uninstall|status` (systemd user unit, no sudo).
- Local proxy endpoints: HTTP 127.0.0.1:8081, SOCKS 127.0.0.1:1081.
- Real speed measurement through the tunnel (Cloudflare speedtest via proxy).
- Direct-vs-tunnel egress IP comparison.
- Official Psiphon binary wiring (`bin/`, fetched from Psiphon-Labs binaries repo).
- Base config `assets/psiphon.config` (official server-list keys, indistinguishable TLS).
- systemd user unit template (hardened, `%h` paths) — source of truth in the
  kernel skill `k-psiphon` (`assets/psiphon.service`), symlinked to
  `~/.config/systemd/user/psiphon.service` via `assets/links.jsonc`.
- Project standards per k-project: CONTRACT.md, Makefile, LICENSE, tests/ scaffold.
- Quality gate green: `make check` = ruff lint + format + pyright (0 errors) +
  5 pytest smoke/behavior tests (help, regions table, active-config write,
  stopped status, busy-port preflight fail-loud). Console entry point
  `psiphon = "psiphon.main:app"` (Typer official pattern; avoids the
  `__init__.main` function shadowing the `psiphon.main` submodule).
