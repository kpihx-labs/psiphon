# Psiphon validation evidence

## Native TUN survey, 2026-10-24

The native packet tunnel, not an application proxy, was exercised with
`psiphon bench -a -s 3 -w 30`. Exact selected/attempted set equality confirms
31/31 codes. Sixteen returned verified HTTPS egress and a download measurement.
Each row is one short observation, not a sustained-speed guarantee.

| Code | Download Mbps |
|---|---:|
| GB | 117.874 |
| CH | 101.260 |
| NL | 92.583 |
| DE | 92.269 |
| PL | 73.785 |
| AT | 70.353 |
| SE | 68.545 |
| LT | 60.090 |
| ES | 55.776 |
| CZ | 54.101 |
| RO | 47.573 |
| RS | 30.871 |
| US | 26.864 |
| CA | 18.517 |
| SG | 7.769 |
| AU | 4.148 |

BE, BG, DK, EE, FI, FR, HU, ID, IE, IN, IT, JP, LV, NO and SK failed readiness
within 30 seconds; none is assigned zero throughput. FR separately connected
at 111.363 Mbps before the full survey. A longer-budget native recheck followed:
`psiphon bench -r DE -r GB -r CH -r FR -r JP -s 5 -w 75 -u`.

| Code | Download Mbps | Upload Mbps |
|---|---:|---:|
| DE | 125.357 | 35.770 |
| FR | 125.107 | 38.407 |
| GB | 112.329 | 31.318 |
| CH | 105.790 | 28.835 |
| JP | 0.023 | 0.150 |

The recheck confirms FR/JP were not permanently unavailable. DE used the same
57.129.25.93 exit as an earlier proxy test that could not measure OVH. This is
evidence of working native traffic now, not proof that native mode alone caused
the difference: time, endpoint, server state and transport selection also differ.
No OpenVPN speed survey was repeated. Historical k-vpn failure counts below were
affected by the subsequently fixed authentication regression and are not a fair
current availability comparison.

After the native tests, the physical default route, Tailscale policy rules and
campus/Tailscale DNS domains were restored; the owned TUN/rules were removed.
A further DE lifecycle check returned 217.160.104.238, with
`1.1.1.1 dev psiphon0 table 18081` and a nonlocal IPv6 route query rejected
with `No route to host`; normal routing was restored after context exit.
Raw observations stay in XDG cache in `bench-20261024T103406.718094Z.jsonl` and
`bench-20261024T104924.063652Z.jsonl`. Measurements use bounded transfers and
include connection/setup overhead; they do not benchmark all servers in a country.

## v2 scope qualification (2026-10-24)

The country/service measurements below are preserved historical v1 proxy evidence,
not native packet-tunnel validation. Version 2 removes service management and uses
`psiphon bench --all --proxy` for an explicit equivalent-scope proxy survey, or
`psiphon bench --all` from a normal terminal for sudo-supervised native attempts. Ordinary status
never performs a region survey. This refactor is validated offline only; no new
bandwidth figures, packet-capable country list or live leak-test claim is made.

Offline refactor validation: `make check` passed with **69 tests**, Ruff lint and
format checks, Python compilation, Pyright **0 errors / 0 warnings**, sdist/wheel
build, and installation of the wheel into an isolated temporary target. The suite
blocks real HTTP requests. Coverage includes all 13 route-mutation failure points,
reverse rollback and rollback-error propagation, numeric-table alias collisions,
resolver/policy conflicts, actual pipe EOF and controller SIGKILL with dummy
processes, engine stop/reap, native channel readiness versus proxy readiness,
PID reuse, explicit benchmark coverage, hash failures and exact packaged licenses.
`uv run --offline --no-sync psiphon -v` reported `2.0.0`; `connect -h` showed native
foreground semantics and short aliases. No root command or live tunnel was run.

Remaining validation gate: privileged native packet connection, DNS routing,
nonlocal IPv6 rejection, transport bypass and exact network restoration on a real
host, using an armed tmux pane in the agent's current window. No country is newly
certified for packet mode by these offline results. No commit or publish occurred.

### Elevation/resolver correction (2026-10-24)

Native UX is now a normal-user command with terminal sudo authentication for only
the network supervisor; setup and all XDG state remain under the caller. The engine
is independently hash-verified as a sealed snapshot and spawned with the caller
UID/GID, not root. Privileged spawn/authentication are mocked in offline tests.
Real EOF/SIGKILL rollback tests still use unprivileged dummy processes.

Correction validation: `make check` passed **89 tests**, Ruff lint/format, Python
compilation, Pyright **0 errors / 0 warnings**, offline sdist/wheel build and the
isolated installed-wheel smoke. New tests cover separate terminal authentication,
no elevation in proxy mode, cancelled/missing authentication, fixed-purpose native
RPC, pipe validation, caller-owned TUN, UID/GID/groups at spawn, user XDG paths,
symlink/mode/owner rejection, sealed-snapshot immutability and tamper detection.
Both external HTTP and actual sudo/ip/sysctl/resolvectl execution are blocked in
the offline test fixture. No sudo authentication, native connection or root
operation ran; the sudo transport and privileged lifecycle still need live validation.

Read-only commands: `resolvectl status`, `resolvectl domain`, `ip -j -4 rule show`,
`ip -j -6 rule show`. Exact blocker: tailscale0 owns `~.` together with
`tail2527bd.ts.net` and `eleves.polytechnique.fr`; Global has
`tail2527bd.ts.net ~ts.net`; wlp0s20f3 has `eleves.polytechnique.fr`. The existing
Tailscale policy rules are at priorities 5210, 5230, 5250 and 5270. Adding a TUN
catch-all would compete with Tailscale DNS, and preserving specific domains needs
transport exceptions absent from the current routing design. Native preflight
therefore refuses before sudo and prints this policy. No DNS setting was changed.

## Complete country survey, 2026-10-24

Command: `make test-live`, an explicit opt-in integration test in the existing
test suite. No standalone benchmark script or new Markdown report is generated.
Execution lasted 14 minutes 34 seconds, approximately 00:45-00:59 UTC.

A fresh engine notice announced 26 codes. Their union with the CLI catalogue
contained 31 codes, all attempted exactly once; no new code was discovered later.
BG, EE, HU, LV and SK were catalogue-only, not in the fresh notice. The test's
successful completion proves coverage, not that every country was usable.

The direct line downloaded at 143.818 Mbps. Measurements used the same file as
the historical OpenVPN survey:
`https://lil1-rbx.speedtest.network.ovh.net/files/100Mb.dat`.
Each usable country received two nominal five-second IPv4 curl transfers through
the explicit HTTP proxy; HTTP/TLS setup is included in actual elapsed time.
Time-bounded curl exit 28 with HTTP 200 and received payload is an expected stop,
not an automatic failure. CF fallback results remain separate from the OVH ranking.

## Measured countries

| Country | Code | OVH median Mbps | Samples Mbps | Verified HTTPS exit |
|---|---|---|---|---|
| France | FR | 59.693 | 58.353, 61.034 | 57.128.117.194 |
| Switzerland | CH | 31.377 | 30.228, 32.526 | 37.46.119.245 |
| Netherlands | NL | 30.198 | 29.123, 31.272 | 51.15.126.27 |
| United Kingdom | GB | 28.584 | 27.704, 29.464 | 77.68.7.188 |
| Austria | AT | 16.905 | 16.749, 17.062 | 130.195.249.106 |
| Poland | PL | 15.465 | 15.649, 15.281 | 57.128.192.44 |
| Sweden | SE | 14.678 | 14.574, 14.782 | 37.46.121.76 |
| Czechia | CZ | 13.918 | 13.290, 14.546 | 5.254.60.98 |
| Serbia | RS | 13.905 | 14.075, 13.734 | 31.3.156.84 |
| Lithuania | LT | 12.477 | 12.267, 12.686 | 188.214.129.42 |
| Spain | ES | 11.129 | 8.624, 13.634 | 217.160.102.118 |
| United States | US | 5.308 | 5.373, 5.242 | 192.241.132.14 |
| Romania | RO | 4.496 | 4.248, 4.744 | 109.163.234.186 |
| India | IN | 2.910 | 2.857, 2.962 | 206.189.141.158 |
| Singapore | SG | 1.914 | 1.782, 2.045 | 152.42.195.9 |
| Canada | CA | 0.459 | 0.813, 0.105 | 154.21.146.118 |
| Australia | AU | 0.328 | 0.183, 0.472 | 134.199.155.155 |
| Japan | JP | 0.105 | 0.026, 0.183 | 172.104.120.138 |

All 18 measured codes were in the fresh fleet notice. The engine's reported
server region matched each requested code, and each exit differed from the
direct line. A subsequent ipwho.is lookup matched all 19 obtained exits to their
requested ISO code (including Germany). This is an independent database check,
not proof of physical server location or acceptance by every site's GeoIP database.

## Non-measured cases

- Germany (DE): HTTPS/public-IP verification succeeded at 57.129.25.93, but both
  OVH requests closed without a response and CF fallback returned HTTP 403.
  It is not a zero-Mbps or globally unusable-country claim.
- Connection/readiness did not succeed within the bound for BE, BG, DK, EE, FI,
  HU, ID, IE, IT, LV, NO and SK. Some were advertised and some catalogue-only.
  A failed trial is not proof of permanent unavailability or a universal network ban.
- Totals: 18 measured, 1 HTTPS-verified without speed, 12 connection failures;
  31/31 attempts, with exact country-set equality verified.

## Service and cleanup validation

After the survey, the repository-owned user unit was installed for FR. HTTP and
SOCKS5h HTTPS both exited at 57.128.117.194. A targeted SIGKILL changed MainPID
3436753 to 3436836; HTTPS recovered automatically. The unit was then stopped,
disabled and removed. The original core configuration was restored.

Final checks found no remaining engine process or test unit, no home-root state
directory and unchanged normal Wi-Fi routing. Subsequent offline regressions also
cover stale PID removal, unrelated-process protection, zombie handling and foreign
runtime symlinks. No OpenVPN benchmark was rerun.

Raw observations and GeoIP annotations are retained in the private application
cache: `$HOME/.cache/psiphon/countries-20261024T004508.894063Z.jsonl`.
Payload files were streamed and discarded, not saved as 100-MB files.

## Historical OpenVPN comparison, not a new test

The complete previous record remains in
[`../k-vpn/BENCHMARKS.md`](../k-vpn/BENCHMARKS.md).

| Observation | Historical k-vpn survey | Current Psiphon survey |
|---|---|---|
| Scope | 95 relay profiles, 13 listed countries, 3 leader rechecks | 31 codes, 26 announced, 2 transfers per usable country |
| Countries with measured download | Japan and Korea Republic of | 18 countries |
| Best observed result | Japan 1.363 Mbps initially, 0.799 on recheck | France 59.693 Mbps median |
| Japan | 0.799 Mbps on the rechecked exit | 0.105 Mbps |
| Direct line control | historical median 167.622 Mbps | current single control 143.818 Mbps |

The endpoint and nominal sample duration match, but times, relays and paths differ;
this is not a simultaneous controlled provider comparison. The older paired series
also found k-vpn Japan 1.861 Mbps versus Psiphon Japan 0.171 Mbps, while Psiphon FR
was 60.815 Mbps. A separate earlier CF smoke was 66.3 Mbps. No universal winner,
sustained-throughput guarantee or automatic default-country change follows.

The local engine is the unchanged official release-candidate artifact with SHA-256
`046ca168da25d2c0e61c1c15e2b73bfbb67f5208112a4c94fe58fc5aab784f19`.
The wrapper is BUSL 1.1; the engine retains upstream GPLv3. Proxy-mode tests do not
claim device-wide routing, IPv6/UDP leak prevention, universal DPI evasion or anonymity.
