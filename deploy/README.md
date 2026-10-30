# Deploy

USERDATA runs on one host as two containers: the server and a Cloudflare
Tunnel that publishes it at `https://v1.aggviz.com`. Nothing listens on a
public port. Data lives in `/srv/data/userdata` and is backed up to B2.

## One-time setup

1. **Tunnel.** In Cloudflare Zero Trust, create a tunnel named `userdata`
   with a public hostname `v1.aggviz.com` pointing to
   `http://userdata:8765`. Store its token in Bitwarden Secrets Manager as
   `userdata-tunnel-token`.
2. **Login.** Copy `authentik-userdata-mcp.yaml` into the stack repo's
   `authentik/blueprints/`; the authentik worker applies it. It creates the
   public client `userdata-mcp` with PKCE, allowed for akadmin only. Then
   `USERDATA_AUTH_ISSUER=https://auth.tail05f41d.ts.net/application/o/userdata-mcp/`
   and `USERDATA_AUTH_AUDIENCE=userdata-mcp`.
3. **SEC.** Set `USERDATA_SEC_USER_AGENT` to a name and contact, as SEC's
   fair-access policy requires.

## Run

```sh
bws run -- docker compose -f deploy/compose.yml up -d --build
```

## Connect Claude

Claude settings, Connectors, Add custom connector, URL
`https://v1.aggviz.com/mcp`, client id `userdata-mcp` under advanced settings, then sign in
with authentik once. It then
works in the Claude apps on phone, web and desktop.
