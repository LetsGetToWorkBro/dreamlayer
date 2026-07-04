# Deploying to dreamlayer.app (Cloudflare Pages)

The site auto-deploys to Cloudflare Pages via
[`.github/workflows/deploy-landing.yml`](../.github/workflows/deploy-landing.yml)
on every push to `main` that touches `landing/`.

## One-time setup (three steps)

### 1. Add the two repository secrets
GitHub → repo **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Where to get it |
|---|---|
| `CLOUDFLARE_API_TOKEN` | Cloudflare dashboard → **My Profile → API Tokens → Create Token** → template **"Edit Cloudflare Pages"** (or a custom token with the *Account · Cloudflare Pages · Edit* permission). |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare dashboard → **Workers & Pages** → the Account ID shown in the right sidebar. |

### 2. Merge to `main`
The workflow only fires on `main`. Merge this branch's PR (or `workflow_dispatch`
it manually from the Actions tab once the workflow is on `main`). The first run
creates a Pages project named **`dreamlayer`** and publishes `landing/`.

### 3. Attach the custom domain
Cloudflare dashboard → **Workers & Pages → dreamlayer → Custom domains → Set up a
domain** → enter `dreamlayer.app`. Because the domain is already registered in the
same Cloudflare account, the DNS records (a `CNAME`/flattened `A` to the Pages
project) are created automatically and TLS is issued within a minute or two. Add
`www.dreamlayer.app` the same way if you want the redirect.

## Local preview
```bash
cd landing && python3 -m http.server 8080   # → http://localhost:8080
```

Everything is static — no build step. The workflow publishes the `landing/`
directory verbatim.
