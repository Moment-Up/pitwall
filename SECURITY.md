# Security policy

## Reporting a problem

Please report security problems **privately**, through GitHub's
[private vulnerability reporting](https://github.com/Moment-Up/pitwall/security/advisories/new), not in a public
issue. Describe what you found, how to reproduce it and what it lets someone do. We reply within 7 days, then agree
a fix and a disclosure date with you.

## What is in scope

- Getting past the access check: reaching the API from another device without the access token or an allowed
  Tailscale identity.
- Leaking the access token, API keys (`secrets.json`) or other private data.
- Making the API (or a page in the browser) run code on the computer running Pitwall.
- The installers and `pitwall update`: installing something other than the published release, or escaping the
  install folder (path traversal in a zip, links, unsafe file permissions).
- Path traversal anywhere else (captures, replays, static files).

Problems in the games, the consoles, uv, Python or other third-party software belong to their own projects.

## Supported versions

Only the latest release gets security fixes. Update with `uv run pitwall update` (docs/install.md, "Updating").

## Running Pitwall safely

- **Never expose port 8770 (or your `PITWALL_HTTP_PORT`) to the internet.** Pitwall is made for your home network;
  for access from elsewhere use Tailscale (docs/install.md), not port forwarding.
- Devices on your network need the access token; keep the link from `uv run pitwall token` to yourself.
- The installers check each download's SHA-256 from the same release. That proves the zip arrived complete and
  unchanged, not who made it: signed installers are future work (docs/releasing.md).
