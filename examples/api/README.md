# HTTP API

Start the API in one terminal, then run any client in another. Every client mints a tenant key with the admin
token first (`POST /v1/keys`), then posts a batch to `POST /v1/moderate`.

```bash
jevmod init                                   # TypeSafe key
export JEVMOD_ADMIN_TOKEN=change-me           # used once per client to mint a tenant key
jevmod api                                    # http://localhost:8080, OpenAPI at /docs
```

```bash
bash examples/api/curl.sh                     # needs curl and python
python examples/api/python_client.py          # standard library only
node examples/api/node_client.mjs             # Node 18+ (global fetch)
```

Each prints the decisions: one object per message with `action`, `category`, `probability` and every score.
Set `JEVMOD_URL` to point at another host. In production, mint one key per tenant and keep the admin token off
the clients.
