# Deploy

USERDATA runs on vm1 next to the tracker MCP and is published the same
way: a Tailscale Funnel container in front of it, at
`https://userdata.tail05f41d.ts.net`. Sign-in is the stack's authentik.
Data lives in `/srv/data/userdata`.

## One-time setup

1. **Login.** Copy `authentik-userdata-mcp.yaml` into the stack repo's
   `authentik/blueprints/`; the authentik worker applies it. It creates
   the public client `userdata-mcp` (PKCE, akadmin only) with issuer
   `https://auth.tail05f41d.ts.net/application/o/userdata-mcp/`.
2. **Funnel key.** The stack's reusable `tag:funnel` key,
   `TS_FUNNEL_AUTHKEY` in vm1's `/srv/basci/secrets.env`.

## Build and run

```sh
ansible-playbook -i "testing,vm1," deploy/install.yml
```

## Connect Claude

Claude settings, Connectors, Add custom connector:
URL `https://userdata.tail05f41d.ts.net/mcp`, client id `userdata-mcp`
under advanced settings. Sign in with authentik once. It then works in
the Claude apps on phone, web and desktop.

## Later: v1.aggviz.com

Needs a Cloudflare tunnel, which needs a token with Account, Cloudflare
Tunnel, Edit. Point the tunnel at `http://userdata:8765` and change
`USERDATA_PUBLIC_URL`.
