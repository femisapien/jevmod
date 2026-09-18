# Public demo on a VPS

The landing page calls `POST https://<host>/demo/check` with one message; the server holds the TypeSafe key and
refuses to spend more than `JEVMOD_DEMO_BUDGET_USD` per month (default $0.50, about 11,000 judged messages at
1,005 tokens each). Per visitor: 6 checks per minute, 40 per day. Repeated texts hit the cache and cost nothing.
Only the origins in `JEVMOD_DEMO_ORIGINS` may call it from a browser.

What it records, so you can see what people try: timestamp, the text (300 chars max), the decision and every
probability, a salted hash of the IP, and the country if Cloudflare is in front. `GET /demo/stats` and
`GET /demo/recent` return it with the admin token.

## One-time setup on Ubuntu/Debian (Hetzner CX22 is plenty)

```bash
# as root, on a fresh VPS
apt-get update && apt-get install -y ca-certificates curl git ufw
curl -fsSL https://get.docker.com | sh
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable

git clone https://github.com/ohernandezdev/jevmod /opt/jevmod && cd /opt/jevmod/deploy/demo
cp ../../.env.example .env
nano .env        # TYPESAFE_API_KEY, JEVMOD_ADMIN_TOKEN (long random), JEVMOD_DEMO_SALT (random),
                 # JEVMOD_DEMO_ORIGINS=https://ohernandezdev.github.io, JEVMOD_DEMO_BUDGET_USD=0.5

IP=$(curl -s https://ifconfig.me); echo "DEMO_HOST=${IP//./-}.sslip.io" >> .env
export $(grep DEMO_HOST .env) && docker compose up -d --build
curl -s https://$DEMO_HOST/demo/health      # {"ok":true,"budget_usd":0.5,"spent_usd":0.0,"open":true}
```

While the repo is private, clone with a fine-grained GitHub token that has read access to this repo only, or
`scp` the tree from your machine; delete the token from the VPS afterwards.

## Day to day

```bash
cd /opt/jevmod/deploy/demo
docker compose logs -f demo                                   # one JSON line per batch
curl -s -H "Authorization: Bearer $JEVMOD_ADMIN_TOKEN" https://$DEMO_HOST/demo/stats
curl -s -H "Authorization: Bearer $JEVMOD_ADMIN_TOKEN" "https://$DEMO_HOST/demo/recent?limit=50"
git pull && docker compose up -d --build                      # update
```

The budget resets on the first of each month. To close the demo at once: `JEVMOD_DEMO_BUDGET_USD=0` in `.env` and
`docker compose up -d`. To wipe what was recorded: `docker compose down -v`.

The page needs the endpoint URL: set `data-demo="https://<host>"` on the demo section in `docs/index.html` (or the
`DEMO_URL` constant, see the page source). Without it the page shows the precomputed results only.
