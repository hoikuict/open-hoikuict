# Windows components

These optional components are bundled with the Windows server package.
Their exact binaries, SHA-256 digests and Caddy module versions are recorded in
`windows_setup/components-lock.json` and covered by the release manifest.

- Caddy: https://github.com/caddyserver/caddy — Apache-2.0; see Caddy-LICENSE.txt.
- Caddy Cloudflare DNS module: https://github.com/caddy-dns/cloudflare — Apache-2.0.
- WinSW: https://github.com/winsw/winsw — MIT; see WinSW-LICENSE.txt.
- cloudflared: https://github.com/cloudflare/cloudflared — Apache-2.0; see cloudflared-LICENSE.txt.

Upstream projects retain their respective copyrights and trademarks.
Caddy v2.11.4 with the Cloudflare v0.2.4 plugin is recovered from the pinned
v2026.9.23.5 application release. Both the archive and extracted executable are
checked by digest before execution. Builds do not contact the mutable Caddy
build service. This preserves the already-reviewed binary; it is not a claim
that its original build can be reproduced from source.

For a future Caddy update, build with fixed Caddy/plugin/xcaddy/Go versions,
retain the module graph, checksums and build flags, and publish a versioned
component asset before changing the reviewed lock. Do not use @latest or
--record-lock to trust a new download automatically.
