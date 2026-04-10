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
2. Fetches semantic model definitions through the Fabric `getDefinition` API, which returns the model in **TMDL** (Tabular Model Definition Language) format
3. Parses TMDL to extract tables, columns (with data types), measures (with DAX expressions), and relationships
4. Executes DAX queries via the Power BI `executeQueries` REST endpoint

## MCP Tools

### `get_semantic_model_schema`

Retrieves the full schema of a Power BI semantic model: tables, columns (with data types), measures (with DAX expressions), and relationships. Use this to understand the model structure before writing DAX queries.

**Inputs:**
- `dataset_id` (string, required) — The Power BI dataset/semantic model ID
- `workspace_id` (string, optional) — Workspace ID to skip auto-detection (faster)

### `execute_dax_query`

Executes a DAX query against a semantic model and returns structured results with column names and rows.

**Inputs:**
- `dataset_id` (string, required) — The Power BI dataset/semantic model ID
- `dax_query` (string, required) — The DAX query to execute

## Prerequisites

- **Python 3.12+** with [UV](https://docs.astral.sh/uv/)
- **Azure AD app registration** (service principal) with `Dataset.Read.All` permission
- Semantic models hosted on **Premium, PPU, Embedded, or Fabric** capacity (see above)
- Service principal added as **Member** of the target workspace

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

The included script creates an app registration, service principal, client secret, and configures permissions:

```bash
./setup_azure_auth.sh
```

Requires the [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli). The script writes credentials directly to `.env`.

### Manual

1. Register an app in **Azure AD (Entra ID)**
2. Create a **client secret**
3. Under API Permissions, add **Power BI Service → Dataset.Read.All** (Application)
4. **Grant admin consent**
5. In **Power BI Admin Portal** → Tenant settings → Developer settings:
   Enable "Allow service principals to use Power BI APIs"
6. In your **Power BI workspace** → Settings → Access:
   Add the service principal as a **Member**

## Configuration

All settings via environment variables (`.env`):

| Variable | Default | Description |
|---|---|---|
| `TENANT_ID` | — | Azure AD tenant ID |
| `CLIENT_ID` | — | Azure AD app (client) ID |
| `CLIENT_SECRET` | — | Azure AD client secret |
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

## Testing

```bash
uv run pytest
```

## License

MIT
