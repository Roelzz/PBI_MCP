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

1. Authenticates as an Azure AD **service principal** via MSAL
2. Discovers workspaces, datasets, and reports via the Power BI REST API
3. Fetches semantic model definitions through the Fabric `getDefinition` API, which returns the model in **TMDL** (Tabular Model Definition Language) format
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

## Prerequisites

- **Python 3.12+** with [UV](https://docs.astral.sh/uv/)
- **Azure AD app registration** with `Dataset.Read.All` API permission (required)
- Optionally add `Workspace.Read.All` and `Report.Read.All` for access beyond workspaces where the service principal is a Member
- Semantic models hosted on **Premium, PPU, Embedded, or Fabric** capacity (see above)
- Service principal added as **Member** of the target workspace (this alone is sufficient for all tools — the extra API permissions are only needed for org-wide access)

## Quick Start

```bash
# Install dependencies
uv sync

# Configure credentials
cp .env.example .env
# Edit .env with your Azure AD credentials (see below)

# Start the server
uv run python main.py
```

Server starts on `http://0.0.0.0:2009` with HTTP/SSE transport.

## Azure AD Setup

### Automated (recommended)

The included script creates an app registration, service principal, certificate, client secret (fallback), and configures permissions including OBO:

```bash
./setup_azure_auth.sh
```

Requires the [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) and `openssl`. The script writes credentials directly to `.env` and generates `cert.pfx` in the project root.

### Manual

1. Register an app in **Azure AD (Entra ID)**
2. Generate a self-signed certificate and upload the public key to the app registration (or create a client secret as fallback)
3. Under API Permissions, add **Power BI Service**:
   - Application: `Dataset.Read.All` (required), `Workspace.Read.All`, `Report.Read.All` (optional)
   - Delegated: `Dataset.Read.All` (required for OBO)
4. **Grant admin consent**
5. Under **Expose an API**, add scope `access_as_user` (required for OBO)
6. In the app manifest, set `requestedAccessTokenVersion: 2`
7. In **Power BI Admin Portal** → Tenant settings → Developer settings:
   Enable "Allow service principals to use Power BI APIs"
8. In your **Power BI workspace** → Settings → Access:
   Add the service principal as a **Member**

> **Note:** Steps 5-6 are only needed for OBO mode (`AUTH_MODE=obo`). For `AUTH_MODE=none`, only the application permissions and workspace membership are required.

## Authentication

The server supports two authentication modes, controlled by `AUTH_MODE` in `.env`:

### `AUTH_MODE=none` (default)

No authentication on the MCP endpoint. The server uses the service principal's certificate to access Power BI. Suitable for local development and trusted networks.

### `AUTH_MODE=obo` (recommended for production)

The MCP endpoint requires a valid Azure AD bearer token. The server validates the token using Azure AD's JWKS endpoint, then exchanges it for a Power BI token via the On-Behalf-Of (OBO) flow. This means:

- Every MCP request must include an `Authorization: Bearer <token>` header
- Power BI access is scoped to the calling user (respects Row-Level Security)
- The service principal still needs a certificate for the OBO exchange

Required settings for OBO mode:
```
AUTH_MODE=obo
MCP_BASE_URL=https://your-mcp-server.example.com
```

### Certificate Auth

The server authenticates to Azure AD using a PFX certificate — no client secrets.

| Setting | Description |
|---|---|
| `CLIENT_CERT_PATH` | Path to PFX certificate file (required) |
| `CLIENT_CERT_PASSPHRASE` | Optional PFX passphrase |

Run `./setup_azure_auth.sh` to generate the certificate and configure the app registration.

### Testing OBO locally

Get a token for the MCP server's API scope using the Azure CLI:

```bash
# Login as yourself
az login

# Get a token for the MCP server's API scope
TOKEN=$(az account get-access-token \
  --resource api://<your-client-id> \
  --query accessToken -o tsv)

# Test the MCP endpoint
curl -H "Authorization: Bearer $TOKEN" http://localhost:2009/mcp
```

> **Note:** The `az account get-access-token --resource` command requires the app registration to have `requestedAccessTokenVersion: 2` in its manifest and the `access_as_user` scope exposed. The setup script configures this automatically.

## Configuration

All settings via environment variables (`.env`):

| Variable | Default | Description |
|---|---|---|
| `TENANT_ID` | — | Azure AD tenant ID |
| `CLIENT_ID` | — | Azure AD app (client) ID |
| `CLIENT_CERT_PATH` | — | Path to PFX certificate (required) |
| `CLIENT_CERT_PASSPHRASE` | — | PFX passphrase (optional) |
| `AUTH_MODE` | `none` | Auth mode: `none` or `obo` |
| `MCP_BASE_URL` | — | Server public URL (required for OBO) |
| `MCP_TRANSPORT` | `http` | Transport type: `http` or `stdio` |
| `MCP_PORT` | `2009` | Server port (HTTP/SSE mode) |
| `LOG_LEVEL` | `INFO` | Log level |

## MCP Client Configuration

### Claude Desktop

Add to your Claude Desktop MCP config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "powerbi": {
      "url": "http://localhost:2009/sse"
    }
  }
}
```

### Copilot Studio

Use the SSE endpoint URL `http://<host>:2009/sse` as the MCP server connection in Copilot Studio's generative actions configuration.

For OBO mode, configure the Copilot Studio connector to acquire a token with audience `api://<client-id>` and scope `api://<client-id>/access_as_user`.

## Testing

```bash
uv run pytest
```

## License

MIT
