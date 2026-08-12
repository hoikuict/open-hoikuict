# Public demo deployment

This repository now supports a public demo mode for Dockge deployments.

## What public demo mode does

- Creates a fresh SQLite database per browser session.
- Uses the packaged anonymized `demo_data/demo-template.sqlite3` as the initial state.
- Resets the demo data by issuing a new session cookie.
- Cleans up expired session databases after the configured TTL.
- Rejects oversized write requests.
- Rejects sessions that exceed the total write budget.
- Stores Web Push subscriptions, delivery targets, and receipts in the same isolated session database.
- Removes those subscriptions automatically when the session database expires.

## Recommended environment values

- `PUBLIC_DEMO_MODE=1`
- `DEMO_SESSION_TTL_MINUTES=120`
- `DEMO_SESSION_INPUT_LIMIT_BYTES=65536`
- `DEMO_MAX_REQUEST_BODY_BYTES=16384`
- `DEMO_SECURE_COOKIES=1`

To enable the opt-in Web Push experience on `demo.hoikuict.net`, also set:

- `HOIKUICT_ENV=production`
- `HOIKUICT_COOKIE_SECURE=1`
- `HOIKUICT_CSRF_ENFORCE=1`
- `HOIKUICT_SECRET_KEY` to a random value of at least 32 characters
- `HOIKUICT_ALLOWED_ORIGINS=https://demo.hoikuict.net`
- `HOIKUICT_PUSH_TRANSPORT=webpush`
- `HOIKUICT_PUSH_VAPID_PUBLIC_KEY` to the public application server key
- `HOIKUICT_PUSH_VAPID_PRIVATE_KEY` to the matching private key
- `HOIKUICT_PUSH_VAPID_SUBJECT` to a maintained `mailto:` or HTTPS contact
- `HOIKUICT_PUBLIC_ORIGIN=https://demo.hoikuict.net`

Keep the VAPID key pair stable across deployments so an existing browser subscription remains usable. Store the private key only in Dockge's environment/secret management; never commit it.

The ordinary production mode still rejects `capture` and `webpush`. The exception applies only when `PUBLIC_DEMO_MODE=1`, the exact public origin is configured, and all Web Push security checks pass.

## Dockge

1. Fork this repository.
2. In Dockge, create a stack from this repository or paste in `compose.yaml`.
3. Copy `.env.example` values into the stack environment editor.
4. Set `CLOUDFLARE_TUNNEL_TOKEN` if you want the stack to publish itself through Cloudflare Tunnel.
5. Start the stack and confirm the app responds on port `8000`.
6. Open `/parent-portal/push-settings`, register a test device, create an attendance confirmation request, and verify `accepted`, `shown`, and `clicked` under `/dev/push-notifications`.

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
- Regenerate the packaged template with SQLite's backup API. Do not copy a live `hoikuict.db` together with `-wal` or `-shm` sidecar files.
