# TODO

Active development backlog for psiphon.

## Next

- [x] Normal-user native command requests sudo for only the network supervisor;
      independently sealed/hash-verified engine drops back to the caller identity.
- [ ] Native DNS coexistence blocker: tailscale0 owns ~. plus Tailscale/campus
      domains. Design verified resolver-route exceptions or an isolated broker
      without changing existing split DNS; do not disable the preflight guard.

- [x] Native TUN implementation via official ConsoleClient, not tun2socks;
      foreground lifecycle, rollback, DNS/IPv6 policy and offline regressions.
- [ ] Privileged live validation in an armed current-window tmux pane: packet-capable
      exit, DNS path, IPv6 block, uplink binding and exact post-exit restoration.
- [ ] Region availability probe: pre-connect region sanity check against
      Psiphon's server list where possible.
- [x] Explicit benchmark observations in private XDG-cache JSONL, no home-root state.
- [ ] Publish remotes (github + gitlab) + `make push` flow — pending KπX validation.

## Ideas

- [ ] Auto-pick region by measured latency/speed (`psiphon auto`).
- [ ] Wire into k-vpn as an alternative provider backend (k-vpn = VPN Gate,
      psiphon = Psiphon fleet) behind one UI.
