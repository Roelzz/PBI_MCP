import asyncio
import base64
import re
from typing import Any

import httpx
from loguru import logger

from .auth import token_manager

BASE_URL = "https://api.powerbi.com/v1.0/myorg"
FABRIC_URL = "https://api.fabric.microsoft.com/v1"


def _parse_tmdl_tables(parts: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Parse TMDL table files into structured table dicts."""
    tables = []
    for part in parts:
        path = part.get("path", "")
        if not path.startswith("definition/tables/") or not path.endswith(".tmdl"):
            continue

        payload = base64.b64decode(part["payload"]).decode("utf-8")
        table = _parse_single_table(payload)
        if table:
            tables.append(table)
    return tables


def _parse_single_table(tmdl: str) -> dict[str, Any] | None:
    """Parse a single TMDL table definition."""
    lines = tmdl.split("\n")
    if not lines or not lines[0].startswith("table "):
        return None

    table_name = lines[0].removeprefix("table ").strip().strip("'")
    columns: list[dict[str, Any]] = []
    measures: list[dict[str, Any]] = []
    is_hidden = False

    i = 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped == "isHidden" and line.startswith("\t") and not line.startswith("\t\t"):
            is_hidden = True

        elif line.startswith("\tcolumn "):
            col, i = _parse_column(lines, i)
            if col:
                columns.append(col)
            continue

        elif line.startswith("\tmeasure "):
            measure, i = _parse_measure(lines, i)
            if measure:
                measures.append(measure)
            continue

        i += 1

    return {
        "name": table_name,
        "is_hidden": is_hidden,
        "columns": columns,
        "measures": measures,
    }


def _parse_column(lines: list[str], start: int) -> tuple[dict[str, Any] | None, int]:
    """Parse a column definition starting at the given line index."""
    header = lines[start].strip()
    col_name = header.removeprefix("column ").strip().strip("'")

    data_type = ""
    is_hidden = False
    description = ""

    i = start + 1
    while i < len(lines):
        line = lines[i]
        if not line.startswith("\t\t"):
            break
        stripped = line.strip()
        if stripped.startswith("dataType:"):
            data_type = stripped.split(":", 1)[1].strip()
        elif stripped == "isHidden":
            is_hidden = True
        elif stripped.startswith("description:"):
            description = stripped.split(":", 1)[1].strip().strip("'").strip('"')
        i += 1

    return {
        "name": col_name,
        "data_type": data_type,
        "is_hidden": is_hidden,
        "description": description,
    }, i


def _parse_measure(lines: list[str], start: int) -> tuple[dict[str, Any] | None, int]:
    """Parse a measure definition starting at the given line index."""
    header = lines[start].removeprefix("\tmeasure ").strip()

    # Measure format: 'Name' = Expression  or  Name = Expression
    # Expression may continue on next lines (indented with \t\t)
    match = re.match(r"'([^']+)'\s*=(.*)", header) or re.match(r"(\S+)\s*=(.*)", header)
    if not match:
        return None, start + 1

    measure_name = match.group(1)
    expression_parts = [match.group(2).strip()]

    i = start + 1
    # Collect continuation lines (expression spans multiple lines at \t\t\t level)
    while i < len(lines):
        line = lines[i]
        if not line.startswith("\t\t"):
            break
        stripped = line.strip()
        # Stop collecting expression at metadata properties
        if stripped.startswith("formatString:") or stripped.startswith("lineageTag:") or stripped.startswith("description:") or stripped == "isHidden" or stripped.startswith("changedProperty") or stripped.startswith("annotation "):
            break
        expression_parts.append(stripped)
        i += 1

    expression = "\n".join(p for p in expression_parts if p)

    # Parse remaining metadata
    format_string = ""
    is_hidden = False
    description = ""
    while i < len(lines):
        line = lines[i]
        if not line.startswith("\t\t"):
            break
        stripped = line.strip()
        if stripped.startswith("formatString:"):
            format_string = stripped.split(":", 1)[1].strip()
        elif stripped == "isHidden":
            is_hidden = True
        elif stripped.startswith("description:"):
            description = stripped.split(":", 1)[1].strip().strip("'").strip('"')
        i += 1

    return {
        "name": measure_name,
        "expression": expression,
        "format_string": format_string,
        "is_hidden": is_hidden,
        "description": description,
    }, i


def _parse_tmdl_relationships(parts: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Parse the TMDL relationships file."""
    for part in parts:
        if part.get("path") == "definition/relationships.tmdl":
            payload = base64.b64decode(part["payload"]).decode("utf-8")
            return _parse_relationships_content(payload)
    return []


def _parse_relationships_content(tmdl: str) -> list[dict[str, Any]]:
    """Parse relationships from TMDL content."""
    relationships = []
    lines = tmdl.split("\n")

    i = 0
    while i < len(lines):
        if lines[i].startswith("relationship "):
            rel: dict[str, Any] = {
                "cross_filtering": "Single",
                "is_active": True,
                "from_table": "",
                "from_column": "",
                "to_table": "",
                "to_column": "",
            }
            i += 1
            while i < len(lines) and lines[i].startswith("\t"):
                stripped = lines[i].strip()
                if stripped.startswith("crossFilteringBehavior:"):
                    value = stripped.split(":", 1)[1].strip()
                    rel["cross_filtering"] = "Both" if value == "bothDirections" else "Single"
                elif stripped.startswith("isActive:"):
                    rel["is_active"] = stripped.split(":", 1)[1].strip().lower() == "true"
                elif stripped.startswith("fromColumn:"):
                    ref = stripped.split(":", 1)[1].strip()
                    # Format: TableName.ColumnName or 'TableName'.ColumnName
                    table, col = _parse_column_ref(ref)
                    rel["from_table"] = table
                    rel["from_column"] = col
                elif stripped.startswith("toColumn:"):
                    ref = stripped.split(":", 1)[1].strip()
                    table, col = _parse_column_ref(ref)
                    rel["to_table"] = table
                    rel["to_column"] = col
                i += 1
            relationships.append(rel)
        else:
            i += 1

    return relationships


def _parse_column_ref(ref: str) -> tuple[str, str]:
    """Parse a TMDL column reference like TableName.ColumnName or TableName.'Column Name'."""
    # Handle quoted table or column names
    parts = ref.split(".", 1)
    if len(parts) == 2:
        table = parts[0].strip().strip("'")
        col = parts[1].strip().strip("'")
        return table, col
    return ref, ""


class PowerBIClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60)
        return self._client

    async def _get_headers(self) -> dict[str, str]:
        token = await token_manager.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _resolve_workspace_id(self, dataset_id: str) -> str:
        """Find the workspace ID for a dataset via the Power BI REST API."""
        headers = await self._get_headers()
        client = await self._get_client()

        # Search across all workspaces the SP has access to
        resp = await client.get(f"{BASE_URL}/groups", headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to list workspaces: {resp.status_code} {resp.text[:200]}")

        for group in resp.json().get("value", []):
            group_id = group["id"]
            ds_resp = await client.get(
                f"{BASE_URL}/groups/{group_id}/datasets/{dataset_id}",
                headers=headers,
            )
            if ds_resp.status_code == 200:
                logger.debug("Dataset '{}' found in workspace '{}'", dataset_id, group_id)
                return group_id

        raise RuntimeError(
            f"Dataset '{dataset_id}' not found in any accessible workspace. "
            "Ensure the service principal is a Member of the workspace."
        )

    async def _get_definition_parts(
        self, workspace_id: str, dataset_id: str
    ) -> list[dict[str, str]]:
        """Fetch TMDL definition via the Fabric getDefinition API (async polling)."""
        headers = await self._get_headers()
        client = await self._get_client()

        url = f"{FABRIC_URL}/workspaces/{workspace_id}/semanticModels/{dataset_id}/getDefinition"
        resp = await client.post(url, headers=headers)

        if resp.status_code == 200:
            return resp.json().get("definition", {}).get("parts", [])

        if resp.status_code == 202:
            operation_url = resp.headers.get("location", "")
            retry_after = int(resp.headers.get("retry-after", "5"))
            result_url = f"{operation_url}/result"

            for _ in range(12):  # Max ~60s of polling
                await asyncio.sleep(retry_after)
                status_resp = await client.get(operation_url, headers=headers)
                if status_resp.status_code != 200:
                    continue
                status = status_resp.json().get("status", "")
                if status == "Succeeded":
                    result_resp = await client.get(result_url, headers=headers)
                    if result_resp.status_code == 200:
                        return result_resp.json().get("definition", {}).get("parts", [])
                    raise RuntimeError(f"Failed to fetch definition result: {result_resp.status_code}")
                if status == "Failed":
                    error = status_resp.json().get("error", {})
                    raise RuntimeError(f"getDefinition failed: {error}")

            raise RuntimeError("getDefinition timed out after polling.")

        if resp.status_code == 403:
            raise RuntimeError(
                f"Access denied for semantic model '{dataset_id}'. "
                "Ensure the service principal has Build permissions and 'Service principals can call Fabric public APIs' is enabled."
            )
        if resp.status_code == 404:
            raise RuntimeError(f"Semantic model '{dataset_id}' not found in workspace '{workspace_id}'.")

        raise RuntimeError(f"getDefinition failed: {resp.status_code} {resp.text[:200]}")

    async def get_semantic_model_schema(
        self, dataset_id: str, workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve full schema via Fabric getDefinition API: tables, columns, measures, relationships."""
        logger.info("Fetching schema for dataset '{}'", dataset_id)

        if not workspace_id:
            workspace_id = await self._resolve_workspace_id(dataset_id)

        parts = await self._get_definition_parts(workspace_id, dataset_id)
        tables = _parse_tmdl_tables(parts)
        relationships = _parse_tmdl_relationships(parts)

        logger.info(
            "Schema retrieved: {} tables, {} columns, {} measures, {} relationships",
            len(tables),
            sum(len(t["columns"]) for t in tables),
            sum(len(t["measures"]) for t in tables),
            len(relationships),
        )

        return {
            "dataset_id": dataset_id,
            "workspace_id": workspace_id,
            "tables": tables,
            "relationships": relationships,
        }

    async def _execute_query(
        self, dataset_id: str, query: str
    ) -> list[dict[str, Any]]:
        """Execute a DAX query via the executeQueries endpoint."""
        url = f"{BASE_URL}/datasets/{dataset_id}/executeQueries"
        body = {
            "queries": [{"query": query}],
            "serializerSettings": {"includeNulls": True},
        }

        headers = await self._get_headers()
        client = await self._get_client()

        logger.debug("POST {} | query: {}", url, query[:100])
        resp = await client.post(url, json=body, headers=headers)

        if resp.status_code == 401:
            raise RuntimeError("Authentication failed. Check TENANT_ID, CLIENT_ID, CLIENT_SECRET.")
        if resp.status_code == 403:
            raise RuntimeError(
                f"Access denied for dataset '{dataset_id}'. "
                "Ensure the service principal has Build permissions and the dataset is in Premium/PPU/Embedded capacity."
            )
        if resp.status_code == 404:
            raise RuntimeError(f"Dataset '{dataset_id}' not found.")
        if resp.status_code == 400:
            error_detail = resp.json().get("error", {}).get("message", resp.text)
            raise RuntimeError(f"Invalid query: {error_detail}")

        resp.raise_for_status()

        data = resp.json()
        tables = data.get("results", [{}])[0].get("tables", [])
        if not tables:
            return []
        return tables[0].get("rows", [])

    async def execute_dax(
        self, dataset_id: str, dax_query: str
    ) -> dict[str, Any]:
        """Execute a DAX query and return structured results."""
        logger.info("Executing DAX on dataset '{}'", dataset_id)
        logger.debug("DAX: {}", dax_query[:200])

        rows = await self._execute_query(dataset_id, dax_query)

        # Clean column keys: "Table[Column]" -> "Column", "[Value]" -> "Value"
        def _clean_key(key: str) -> str:
            if "[" in key and key.endswith("]"):
                return key[key.index("[") + 1 : -1]
            return key.strip("[]")

        columns: list[str] = []
        if rows:
            columns = [_clean_key(k) for k in rows[0].keys()]

        clean_rows = [
            {_clean_key(k): v for k, v in row.items()} for row in rows
        ]

        logger.info("Query returned {} rows, {} columns", len(clean_rows), len(columns))
        return {
            "dataset_id": dataset_id,
            "columns": columns,
            "rows": clean_rows,
            "row_count": len(clean_rows),
        }


powerbi_client = PowerBIClient()
