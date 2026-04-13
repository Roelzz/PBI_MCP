# Power BI MCP Server

Self-hosted [MCP](https://modelcontextprotocol.io/) server for querying Power BI semantic models. Retrieves model schemas (tables, columns, measures, relationships) and executes DAX queries — all via the Power BI REST API and Microsoft Fabric API.

Built with [FastMCP](https://github.com/jlowin/fastmcp) (Python). Compatible with any MCP client including Claude Desktop and Microsoft Copilot Studio.

## Capacity Requirements

This server calls the Power BI REST API (`executeQueries`) and Microsoft Fabric API (`getDefinition`). These APIs are only available on datasets hosted in one of the following capacities:

| Capacity | SKU | Notes |
|---|---|---|
| **Power BI Premium** | P1–P5 | Org-wide dedicated capacity |
| **Power BI Premium Per User** | PPU | Per-user Premium license |
| **Power BI Embedded** | A/EM | Azure-provisioned capacity for embedding |
| **Microsoft Fabric** | F2+ | Any Fabric capacity — includes full Power BI semantic model API access |

Datasets on shared (Pro-only) capacity **will not work** — the `executeQueries` and `getDefinition` endpoints return 403.

## How It Works

1. Authenticates as an Azure AD **service principal** via MSAL (certificate-based)
2. Discovers workspaces, datasets, and reports via the Power BI REST API
3. Fetches semantic model definitions through the Fabric `getDefinition` API (TMDL format)
4. Parses TMDL to extract tables, columns (with data types), measures (with DAX expressions), and relationships
5. Executes DAX queries via the Power BI `executeQueries` REST endpoint

All API calls include automatic retry handling for rate limiting (HTTP 429).

## MCP Tools

### Discovery

#### `list_workspaces`

Lists all Power BI workspaces accessible to the service principal. Use this as a starting point to discover available datasets and reports.

**Inputs:** None

#### `list_datasets`

Lists datasets (semantic models) in a workspace, or across all accessible workspaces when `workspace_id` is omitted.

**Inputs:**
- `workspace_id` (string, optional) — Scope to a single workspace (faster). Omit to list across all workspaces.

#### `list_reports`

Lists reports in a workspace, or across all accessible workspaces when `workspace_id` is omitted.

**Inputs:**
- `workspace_id` (string, optional) — Scope to a single workspace (faster). Omit to list across all workspaces.

### Schema & Queries

#### `get_semantic_model_schema`

Retrieves the full schema of a Power BI semantic model: tables, columns (with data types), measures (with DAX expressions), and relationships. Use this to understand the model structure before writing DAX queries.

**Inputs:**
- `dataset_id` (string, required) — The Power BI dataset/semantic model ID
- `workspace_id` (string, optional) — Workspace ID to skip auto-detection (faster)

#### `execute_dax_query`

Executes a DAX query against a semantic model and returns structured results with column names and rows.

**Inputs:**
- `dataset_id` (string, required) — The Power BI dataset/semantic model ID
- `dax_query` (string, required) — The DAX query to execute

### Typical Flow

```
list_workspaces → list_datasets(workspace_id) → get_semantic_model_schema(dataset_id) → execute_dax_query(dataset_id, dax_query)
```

## Authentication

The server uses **certificate-based authentication** — no client secrets. A PFX certificate is used by MSAL to authenticate the service principal to Azure AD. Two auth modes control how the MCP endpoint itself is protected:

### Why certificates instead of client secrets?

- **Can't be copy-pasted** — a certificate file is harder to accidentally leak than a string
- **No secrets in `.env`** — only a file path, not a credential value
- **Stronger cryptography** — RSA key pair vs a shared secret string
- **The certificate must be uploaded to the app registration** so Azure AD can validate the signature when the server requests a token

### Auth Modes

```mermaid
graph LR
    subgraph "AUTH_MODE=none"
        A[MCP Client] -->|no auth| B[MCP Server]
        B -->|certificate| C[Azure AD]
        C -->|service principal token| D[Power BI API]
    end
```

```mermaid
graph LR
    subgraph "AUTH_MODE=obo"
        A[MCP Client] -->|Bearer token| B[MCP Server]
        B -->|validate JWT| C[Azure AD JWKS]
        B -->|OBO + certificate| D[Azure AD Token]
        D -->|user-scoped token| E[Power BI API]
    end
```

#### `AUTH_MODE=none` (default)

No authentication on the MCP endpoint. The server uses the service principal's certificate to access Power BI via client credentials. All requests use the same service principal identity.

**Use for:** Local development, trusted networks, MCP Inspector testing.

#### `AUTH_MODE=obo` (recommended for production)

The MCP endpoint requires a valid Azure AD bearer token. The server:
1. Validates the token using Azure AD's JWKS endpoint (supports both v1.0 and v2.0 tokens)
2. Exchanges it for a Power BI token via the On-Behalf-Of (OBO) flow
3. Power BI access is scoped to the calling user — respects Row-Level Security (RLS)

**Use for:** Production deployments, Copilot Studio integration.

Required `.env` settings:
```
AUTH_MODE=obo
MCP_BASE_URL=https://your-mcp-server.example.com
```

## Prerequisites

- **Python 3.12+** with [UV](https://docs.astral.sh/uv/)
- **Azure CLI** (`az`) and **OpenSSL** for setup
- **Azure AD app registration** with a certificate credential
- Semantic models hosted on **Premium, PPU, Embedded, or Fabric** capacity
- Service principal added as **Member** of the target Power BI workspace

## Quick Start

```bash
# Install dependencies
uv sync

# Run the setup script (creates app registration, certificate, permissions)
./setup_azure_auth.sh

# Or configure manually: copy .env.example and edit
cp .env.example .env

# Start the server
uv run python main.py
```

Server starts on `http://0.0.0.0:2009` with Streamable HTTP transport.

## Azure AD Setup

### Automated (recommended)

The setup script creates an app registration, service principal, certificate, and configures all permissions including OBO:

```bash
./setup_azure_auth.sh
```

Requires the [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) and `openssl`. Generates `cert.pfx` in the project root and writes configuration to `.env`.

### Manual

1. Register an app in **Azure AD (Entra ID)**
2. Generate a self-signed certificate:
   ```bash
   openssl req -x509 -newkey rsa:2048 -keyout private.key -out cert.pem -days 365 -nodes -subj "/CN=PowerBI-MCP-Server"
   openssl pkcs12 -export -out cert.pfx -inkey private.key -in cert.pem -passout pass:
   rm private.key
   ```
3. Upload the certificate to the app registration:
   ```bash
   az ad app credential reset --id <your-client-id> --cert @cert.pem --append
   ```
4. Under **API Permissions**, add **Power BI Service**:
   - Application: `Dataset.Read.All` (required), `Workspace.Read.All`, `Report.Read.All` (optional)
   - Delegated: `Dataset.Read.All` (required for OBO)
5. **Grant admin consent**
6. Under **Expose an API**:
   - Set Application ID URI to `api://<your-client-id>`
   - Add scope `access_as_user` (type: User)
7. In the app **Manifest**, set `requestedAccessTokenVersion: 2`
8. In **Power BI Admin Portal** → Tenant settings → Developer settings:
   Enable "Allow service principals to use Power BI APIs"
9. In your **Power BI workspace** → Settings → Access:
   Add the service principal as a **Member**

> Steps 6-7 are only needed for `AUTH_MODE=obo`. For `AUTH_MODE=none`, only application permissions and workspace membership are required.

## Configuration

All settings via environment variables (`.env`):

| Variable | Default | Description |
|---|---|---|
| `TENANT_ID` | — | Azure AD tenant ID |
| `CLIENT_ID` | — | Azure AD app (client) ID |
| `CLIENT_CERT_PATH` | — | Path to PFX certificate file (required, use absolute path) |
| `CLIENT_CERT_PASSPHRASE` | — | PFX passphrase (optional) |
| `AUTH_MODE` | `none` | Auth mode: `none` or `obo` |
| `MCP_BASE_URL` | — | Server public URL (required for `obo`) |
| `MCP_TRANSPORT` | `http` | Transport type: `http` or `stdio` |
| `MCP_PORT` | `2009` | Server port (HTTP mode) |
| `LOG_LEVEL` | `INFO` | Log level |

## Testing Locally

### Testing with `AUTH_MODE=none`

Start the server and connect MCP Inspector — no auth needed:

```bash
# Start the server
uv run python main.py

# In another terminal
npx @modelcontextprotocol/inspector http://localhost:2009/mcp
```

MCP Inspector opens in your browser. Click **List Tools** to see all available tools, then call them directly.

### Testing OBO with curl

OBO requires a valid Azure AD token. Here's the full flow:

**1. Get a token:**

```bash
# Login to the correct tenant
az login --tenant <your-tenant-id>

# Get a token for the MCP server's API scope
TOKEN=$(az account get-access-token \
  --resource "api://<your-client-id>" \
  --query accessToken -o tsv)
```

> **Note:** Azure CLI often returns v1.0 tokens (issuer `https://sts.windows.net/...`) even when `requestedAccessTokenVersion` is set to 2. The server accepts both v1.0 and v2.0 tokens.

**2. Initialize an MCP session:**

```bash
INIT=$(curl -s -D - \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -X POST http://localhost:2009/mcp \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}')

SESSION=$(echo "$INIT" | grep -i mcp-session-id | tr -d '\r' | awk '{print $2}')
echo "Session: $SESSION"
```

**3. Call a tool:**

```bash
curl -s \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SESSION" \
  -X POST http://localhost:2009/mcp \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"list_workspaces","arguments":{}},"id":2}'
```

### Testing OBO with MCP Inspector

MCP Inspector's CLI `--header` flag does **not** forward custom headers to the MCP server — this is a [known limitation](https://github.com/modelcontextprotocol/inspector/issues/879).

**Workaround — use the Web UI:**

1. Start MCP Inspector: `npx @modelcontextprotocol/inspector`
2. In the browser UI, select **Streamable HTTP** transport
3. Enter the server URL: `http://localhost:2009/mcp`
4. In the **Bearer Token** field, paste your token (from `az account get-access-token`)
5. Click **Connect**

**Alternative:** Test tools with `AUTH_MODE=none` in MCP Inspector, and verify OBO auth separately with curl.

## Production Deployment

### Architecture

```mermaid
graph LR
    A[Copilot Studio] -->|HTTPS + Bearer token| B[Reverse Proxy<br>Traefik / Caddy]
    B -->|HTTP :2009| C[MCP Server<br>FastMCP + Python]
    C -->|OBO + Certificate| D[Azure AD]
    D -->|User-scoped token| E[Power BI API]
```

### Requirements

- **HTTPS is mandatory** — Copilot Studio requires a trusted TLS certificate (self-signed won't work)
- **Public DNS** — your server needs a domain name reachable from Microsoft's cloud
- **Port 443** — open in your router/firewall

### Deploying on Coolify (Nixpacks)

Coolify auto-detects Python/UV projects via `pyproject.toml` and `uv.lock`:

1. Create a new service in Coolify, point to your Git repository
2. Coolify/Nixpacks runs `uv sync --no-dev --frozen` automatically
3. Set the start command: `uv run python main.py`
4. Configure environment variables in Coolify's UI:
   ```
   TENANT_ID=<your-tenant-id>
   CLIENT_ID=<your-client-id>
   CLIENT_CERT_PATH=/app/cert.pfx
   AUTH_MODE=obo
   MCP_BASE_URL=https://your-domain.com
   MCP_TRANSPORT=http
   MCP_PORT=2009
   ```
5. Mount `cert.pfx` into the container (add as a persistent file or base64-encode in an env var and decode at startup)
6. Assign your domain in Coolify — Traefik handles TLS termination and Let's Encrypt certificates automatically

### Alternative: Caddy as reverse proxy

If not using Coolify's built-in Traefik:

```
your-domain.com {
    reverse_proxy localhost:2009
}
```

Caddy automatically provisions and renews Let's Encrypt certificates.

## Copilot Studio Connection

### Connecting your agent

1. In Copilot Studio, go to **Tools → Add Tool → New Tool → MCP**
2. Enter your server's HTTPS URL: `https://your-domain.com/mcp`
3. **Generative Orchestration** must be enabled on your agent
4. Copilot Studio auto-discovers all tools from the server

> **Important:** Copilot Studio requires **Streamable HTTP** transport. SSE transport is deprecated.

### Configuring OBO authentication

For user-scoped Power BI access via OBO:

1. In Copilot Studio, configure OAuth on the MCP connection:
   - **Client ID**: your app registration's client ID
   - **Tenant ID**: your Azure AD tenant ID
   - **Authorization URL**: `https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/authorize`
   - **Token URL**: `https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token`
   - **Scope**: `api://<client-id>/access_as_user`
2. Copilot Studio acquires a token for each user session and sends it in the `Authorization` header
3. The MCP server validates the token and exchanges it for a Power BI token scoped to that user

## MCP Client Configuration

### Claude Desktop

Add to your Claude Desktop MCP config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "powerbi": {
      "url": "http://localhost:2009/mcp"
    }
  }
}
```

## Testing

```bash
uv run pytest
```

## License

MIT
