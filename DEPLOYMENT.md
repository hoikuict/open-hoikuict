# Public demo deployment

This repository now supports a public demo mode for Dockge deployments.

## What public demo mode does

- Creates a fresh SQLite database per browser session.
- Resets the demo data by issuing a new session cookie.
- Cleans up expired session databases after the configured TTL.
- Rejects oversized write requests.
- Rejects sessions that exceed the total write budget.

## Recommended environment values

- `PUBLIC_DEMO_MODE=1`
- `DEMO_SESSION_TTL_MINUTES=120`
- `DEMO_SESSION_INPUT_LIMIT_BYTES=65536`
- `DEMO_MAX_REQUEST_BODY_BYTES=16384`
- `DEMO_SECURE_COOKIES=1`

## Dockge

1. Fork this repository.
2. In Dockge, create a stack from this repository or paste in `compose.yaml`.
3. Copy `.env.example` values into the stack environment editor.
4. Set `CLOUDFLARE_TUNNEL_TOKEN` if you want the stack to publish itself through Cloudflare Tunnel.
5. Start the stack and confirm the app responds on port `8000`.

## Cloudflare

If you already run `cloudflared` elsewhere, you can remove the `cloudflared` service and point your existing tunnel at `http://app:8000` on the same Docker network or at the host port you exposed from Dockge.

If you use the bundled `cloudflared` service:

1. Create a Cloudflare Tunnel in the dashboard.
2. Add a public hostname for your chosen domain.
3. Point that hostname to `http://app:8000`.
4. Copy the tunnel token into `CLOUDFLARE_TUNNEL_TOKEN`.
5. Redeploy the stack.

## Notes

- Public demo mode keeps runtime session data under `./runtime`, which is ignored by git.
- No persistent volume is configured on purpose, so demo sessions disappear on redeploy or container recreation.
