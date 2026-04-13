import base64
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.powerbi import (
    PowerBIClient,
    _parse_single_table,
    _parse_relationships_content,
    _parse_tmdl_tables,
    _parse_tmdl_relationships,
)


SAMPLE_TABLE_TMDL = """table Sales
\tlineageTag: abc-123

\tcolumn Amount
\t\tdataType: double
\t\tlineageTag: col-1
\t\tsummarizeBy: sum
\t\tsourceColumn: Amount

\tcolumn Date
\t\tdataType: dateTime
\t\tisHidden
\t\tformatString: General Date
\t\tlineageTag: col-2
\t\tsourceColumn: Date

\t\tannotation SummarizationSetBy = Automatic

\tcolumn ProductID
\t\tdataType: int64
\t\tlineageTag: col-3
\t\tsourceColumn: ProductID

\tmeasure 'Total Sales' = SUM(Sales[Amount])
\t\tformatString: #,0.00
\t\tlineageTag: meas-1

\t\tannotation PBI_FormatHint = {"isCustom":true}

\tmeasure 'Avg Sales' =
\t\t\tVAR Total = SUM(Sales[Amount])
\t\t\tVAR Count = COUNTROWS(Sales)
\t\t\tRETURN Total / Count
\t\tformatString: 0.00
\t\tlineageTag: meas-2
"""

SAMPLE_PRODUCTS_TMDL = """table Products
\tlineageTag: def-456

\tcolumn ProductID
\t\tdataType: int64
\t\tlineageTag: col-10
\t\tsourceColumn: ProductID

\tcolumn ProductName
\t\tdataType: string
\t\tdescription: Name of the product
\t\tlineageTag: col-11
\t\tsourceColumn: ProductName
"""

SAMPLE_RELATIONSHIPS_TMDL = """relationship rel-1
\tcrossFilteringBehavior: bothDirections
\tfromColumn: Sales.ProductID
\ttoColumn: Products.ProductID

relationship rel-2
\tisActive: false
\tfromColumn: Sales.Date
\ttoColumn: Calendar.Date
"""


@pytest.fixture
def powerbi_client() -> PowerBIClient:
    return PowerBIClient()


def test_parse_single_table() -> None:
    """TMDL table parsing extracts columns and measures."""
    table = _parse_single_table(SAMPLE_TABLE_TMDL)

    assert table["name"] == "Sales"
    assert table["is_hidden"] is False
    assert len(table["columns"]) == 3

    amount = table["columns"][0]
    assert amount["name"] == "Amount"
    assert amount["data_type"] == "double"
    assert amount["is_hidden"] is False

    date = table["columns"][1]
    assert date["name"] == "Date"
    assert date["data_type"] == "dateTime"
    assert date["is_hidden"] is True

    assert len(table["measures"]) == 2
    total = table["measures"][0]
    assert total["name"] == "Total Sales"
    assert total["expression"] == "SUM(Sales[Amount])"
    assert total["format_string"] == "#,0.00"

    avg = table["measures"][1]
    assert avg["name"] == "Avg Sales"
    assert "VAR Total = SUM(Sales[Amount])" in avg["expression"]
    assert "RETURN Total / Count" in avg["expression"]


def test_parse_relationships() -> None:
    """TMDL relationship parsing extracts tables, columns, and properties."""
    rels = _parse_relationships_content(SAMPLE_RELATIONSHIPS_TMDL)

    assert len(rels) == 2

    r1 = rels[0]
    assert r1["from_table"] == "Sales"
    assert r1["from_column"] == "ProductID"
    assert r1["to_table"] == "Products"
    assert r1["to_column"] == "ProductID"
    assert r1["cross_filtering"] == "Both"
    assert r1["is_active"] is True

    r2 = rels[1]
    assert r2["is_active"] is False
    assert r2["cross_filtering"] == "Single"
    assert r2["from_table"] == "Sales"
    assert r2["to_table"] == "Calendar"


def test_parse_tmdl_tables_from_parts() -> None:
    """Parsing TMDL parts extracts tables from base64-encoded payloads."""
    parts = [
        {"path": "definition/tables/Sales.tmdl", "payload": base64.b64encode(SAMPLE_TABLE_TMDL.encode()).decode()},
        {"path": "definition/tables/Products.tmdl", "payload": base64.b64encode(SAMPLE_PRODUCTS_TMDL.encode()).decode()},
        {"path": "definition/relationships.tmdl", "payload": base64.b64encode(b"").decode()},
        {"path": "definition/model.tmdl", "payload": base64.b64encode(b"").decode()},
    ]

    tables = _parse_tmdl_tables(parts)
    assert len(tables) == 2
    assert tables[0]["name"] == "Sales"
    assert tables[1]["name"] == "Products"
    assert tables[1]["columns"][1]["description"] == "Name of the product"


def test_parse_tmdl_relationships_from_parts() -> None:
    """Parsing TMDL parts extracts relationships from base64-encoded payload."""
    parts = [
        {"path": "definition/relationships.tmdl", "payload": base64.b64encode(SAMPLE_RELATIONSHIPS_TMDL.encode()).decode()},
    ]
    rels = _parse_tmdl_relationships(parts)
    assert len(rels) == 2


def test_parse_hidden_table() -> None:
    """Hidden table flag is parsed correctly."""
    tmdl = "table HiddenTable\n\tisHidden\n\n\tcolumn ID\n\t\tdataType: int64\n"
    table = _parse_single_table(tmdl)
    assert table["is_hidden"] is True


async def test_execute_dax(powerbi_client: PowerBIClient) -> None:
    """Execute DAX returns cleaned rows and columns."""
    mock_rows = [
        {"Sales[ProductName]": "Widget", "Sales[TotalSales]": 1500.0},
        {"Sales[ProductName]": "Gadget", "Sales[TotalSales]": 2300.0},
    ]

    with patch.object(powerbi_client, "_execute_query", return_value=mock_rows):
        result = await powerbi_client.execute_dax("test-id", "EVALUATE Sales")

    assert result["dataset_id"] == "test-id"
    assert result["columns"] == ["ProductName", "TotalSales"]
    assert result["row_count"] == 2
    assert result["rows"][0]["ProductName"] == "Widget"
    assert result["rows"][1]["TotalSales"] == 2300.0


async def test_execute_dax_bracket_keys(powerbi_client: PowerBIClient) -> None:
    """Execute DAX handles [Value] style keys from ROW/SUMMARIZE queries."""
    mock_rows = [{"[Count]": 42}]

    with patch.object(powerbi_client, "_execute_query", return_value=mock_rows):
        result = await powerbi_client.execute_dax("test-id", "EVALUATE ROW(\"Count\", 42)")

    assert result["columns"] == ["Count"]
    assert result["rows"][0]["Count"] == 42


async def test_execute_dax_empty(powerbi_client: PowerBIClient) -> None:
    """Execute DAX handles empty results."""
    with patch.object(powerbi_client, "_execute_query", return_value=[]):
        result = await powerbi_client.execute_dax("test-id", "EVALUATE FILTER(Sales, FALSE)")

    assert result["row_count"] == 0
    assert result["columns"] == []
    assert result["rows"] == []


async def test_error_401(powerbi_client: PowerBIClient) -> None:
    """Auth error raises RuntimeError with descriptive message."""
    mock_resp = AsyncMock()
    mock_resp.status_code = 401

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp
    mock_client.is_closed = False
    powerbi_client._client = mock_client

    with patch("src.powerbi.token_manager.get_token", return_value="fake-token"):
        with pytest.raises(RuntimeError, match="Authentication failed"):
            await powerbi_client._execute_query("test-id", "EVALUATE Sales")


async def test_error_403(powerbi_client: PowerBIClient) -> None:
    """Permission error raises RuntimeError with descriptive message."""
    mock_resp = AsyncMock()
    mock_resp.status_code = 403

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp
    mock_client.is_closed = False
    powerbi_client._client = mock_client

    with patch("src.powerbi.token_manager.get_token", return_value="fake-token"):
        with pytest.raises(RuntimeError, match="Access denied"):
            await powerbi_client._execute_query("test-id", "EVALUATE Sales")


async def test_error_404(powerbi_client: PowerBIClient) -> None:
    """Not found error raises RuntimeError."""
    mock_resp = AsyncMock()
    mock_resp.status_code = 404

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp
    mock_client.is_closed = False
    powerbi_client._client = mock_client

    with patch("src.powerbi.token_manager.get_token", return_value="fake-token"):
        with pytest.raises(RuntimeError, match="not found"):
            await powerbi_client._execute_query("test-id", "EVALUATE Sales")


async def test_error_400(powerbi_client: PowerBIClient) -> None:
    """Invalid query raises RuntimeError with API error detail."""
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"error": {"message": "Syntax error in DAX"}}
    mock_resp.text = "Bad Request"

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp
    mock_client.is_closed = False
    powerbi_client._client = mock_client

    with patch("src.powerbi.token_manager.get_token", return_value="fake-token"):
        with pytest.raises(RuntimeError, match="Syntax error in DAX"):
            await powerbi_client._execute_query("test-id", "INVALID DAX")


async def test_mcp_tool_schema_error() -> None:
    """MCP tool returns error dict on failure instead of raising."""
    from src.server import get_semantic_model_schema

    with patch("src.server.powerbi_client.get_semantic_model_schema", side_effect=RuntimeError("test error")):
        result = await get_semantic_model_schema("bad-id")

    assert result["error"] == "test error"


async def test_mcp_tool_execute_error() -> None:
    """MCP tool returns error dict on failure instead of raising."""
    from src.server import execute_dax_query

    with patch("src.server.powerbi_client.execute_dax", side_effect=RuntimeError("query failed")):
        result = await execute_dax_query("bad-id", "INVALID")

    assert result["error"] == "query failed"


# --- 429 Retry Tests ---


async def test_retry_on_429(powerbi_client: PowerBIClient) -> None:
    """429 response triggers retry and succeeds on second attempt."""
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.headers = {"Retry-After": "0"}

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {"value": []}

    mock_client = AsyncMock()
    mock_client.request.side_effect = [resp_429, resp_200]
    mock_client.is_closed = False
    powerbi_client._client = mock_client

    with patch("src.powerbi.token_manager.get_token", return_value="fake-token"):
        with patch("src.powerbi.asyncio.sleep", new_callable=AsyncMock):
            resp = await powerbi_client._request("GET", "https://example.com/test")

    assert resp.status_code == 200
    assert mock_client.request.call_count == 2


async def test_retry_on_429_exhausted(powerbi_client: PowerBIClient) -> None:
    """429 retries exhausted returns the 429 response."""
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.headers = {"Retry-After": "0"}

    mock_client = AsyncMock()
    mock_client.request.return_value = resp_429
    mock_client.is_closed = False
    powerbi_client._client = mock_client

    with patch("src.powerbi.token_manager.get_token", return_value="fake-token"):
        with patch("src.powerbi.asyncio.sleep", new_callable=AsyncMock):
            resp = await powerbi_client._request("GET", "https://example.com/test")

    assert resp.status_code == 429
    assert mock_client.request.call_count == 4  # initial + 3 retries


# --- list_workspaces Tests ---


async def test_list_workspaces(powerbi_client: PowerBIClient) -> None:
    """List workspaces returns structured workspace data."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "value": [
            {"id": "ws-1", "name": "Sales Workspace", "type": "Workspace", "state": "Active"},
            {"id": "ws-2", "name": "Marketing", "type": "Workspace", "state": "Active"},
        ]
    }

    with patch.object(powerbi_client, "_request", return_value=mock_resp):
        result = await powerbi_client.list_workspaces()

    assert result["count"] == 2
    assert result["workspaces"][0]["id"] == "ws-1"
    assert result["workspaces"][0]["name"] == "Sales Workspace"
    assert result["workspaces"][1]["id"] == "ws-2"


async def test_list_workspaces_empty(powerbi_client: PowerBIClient) -> None:
    """List workspaces with no accessible workspaces."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"value": []}

    with patch.object(powerbi_client, "_request", return_value=mock_resp):
        result = await powerbi_client.list_workspaces()

    assert result["count"] == 0
    assert result["workspaces"] == []


async def test_mcp_tool_list_workspaces_error() -> None:
    """MCP tool returns error dict on failure."""
    from src.server import list_workspaces

    with patch("src.server.powerbi_client.list_workspaces", side_effect=RuntimeError("auth failed")):
        result = await list_workspaces()

    assert result["error"] == "auth failed"


# --- list_datasets Tests ---


async def test_list_datasets(powerbi_client: PowerBIClient) -> None:
    """List datasets returns structured dataset data."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "value": [
            {"id": "ds-1", "name": "Sales Model", "configuredBy": "user@test.com", "isRefreshable": True},
            {"id": "ds-2", "name": "HR Model", "configuredBy": "admin@test.com", "isRefreshable": False},
        ]
    }

    with patch.object(powerbi_client, "_request", return_value=mock_resp):
        result = await powerbi_client.list_datasets("ws-1")

    assert result["workspace_id"] == "ws-1"
    assert result["count"] == 2
    assert result["datasets"][0]["id"] == "ds-1"
    assert result["datasets"][0]["configured_by"] == "user@test.com"
    assert result["datasets"][1]["is_refreshable"] is False


async def test_list_datasets_empty(powerbi_client: PowerBIClient) -> None:
    """List datasets for workspace with no datasets."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"value": []}

    with patch.object(powerbi_client, "_request", return_value=mock_resp):
        result = await powerbi_client.list_datasets("ws-1")

    assert result["count"] == 0
    assert result["datasets"] == []


async def test_mcp_tool_list_datasets_error() -> None:
    """MCP tool returns error dict on failure."""
    from src.server import list_datasets

    with patch("src.server.powerbi_client.list_datasets", side_effect=RuntimeError("not found")):
        result = await list_datasets("bad-ws")

    assert result["error"] == "not found"


# --- list_reports Tests ---


async def test_list_reports(powerbi_client: PowerBIClient) -> None:
    """List reports returns structured report data."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "value": [
            {
                "id": "rpt-1", "name": "Sales Report", "datasetId": "ds-1",
                "reportType": "PowerBIReport", "webUrl": "https://app.powerbi.com/reports/rpt-1",
            },
        ]
    }

    with patch.object(powerbi_client, "_request", return_value=mock_resp):
        result = await powerbi_client.list_reports("ws-1")

    assert result["workspace_id"] == "ws-1"
    assert result["count"] == 1
    assert result["reports"][0]["id"] == "rpt-1"
    assert result["reports"][0]["dataset_id"] == "ds-1"
    assert result["reports"][0]["report_type"] == "PowerBIReport"


async def test_list_reports_empty(powerbi_client: PowerBIClient) -> None:
    """List reports for workspace with no reports."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"value": []}

    with patch.object(powerbi_client, "_request", return_value=mock_resp):
        result = await powerbi_client.list_reports("ws-1")

    assert result["count"] == 0
    assert result["reports"] == []


async def test_mcp_tool_list_reports_error() -> None:
    """MCP tool returns error dict on failure."""
    from src.server import list_reports

    with patch("src.server.powerbi_client.list_reports", side_effect=RuntimeError("forbidden")):
        result = await list_reports("bad-ws")

    assert result["error"] == "forbidden"


# --- Auth: credential selection tests ---


def test_credential_selection_cert(tmp_path) -> None:
    """CLIENT_CERT_PATH set returns certificate dict."""
    pfx = tmp_path / "cert.pfx"
    pfx.touch()
    with patch.dict(os.environ, {
        "TENANT_ID": "t", "CLIENT_ID": "c",
        "CLIENT_CERT_PATH": str(pfx), "CLIENT_CERT_PASSPHRASE": "secret",
    }):
        from src.config import Settings
        s = Settings()
        cred = s.client_credential
        assert isinstance(cred, dict)
        assert cred["private_key_pfx_path"] == str(pfx)
        assert cred["passphrase"] == "secret"


def test_credential_selection_no_cert() -> None:
    """Raises ValueError when CLIENT_CERT_PATH is not set."""
    with patch.dict(os.environ, {
        "TENANT_ID": "t", "CLIENT_ID": "c",
        "CLIENT_CERT_PATH": "",
    }):
        from src.config import Settings
        s = Settings()
        with pytest.raises(ValueError, match="CLIENT_CERT_PATH or CLIENT_CERT_BASE64 must be set"):
            _ = s.client_credential


# --- Auth: OBO token manager tests ---


async def test_obo_token_acquisition() -> None:
    """OBO flow called when user assertion is set."""
    from src.auth import PowerBITokenManager, set_user_assertion

    tm = PowerBITokenManager()
    mock_app = MagicMock()
    mock_app.acquire_token_on_behalf_of.return_value = {"access_token": "obo-token"}
    tm._app = mock_app

    set_user_assertion("user-jwt")
    token = await tm.get_token()

    assert token == "obo-token"
    mock_app.acquire_token_on_behalf_of.assert_called_once_with(
        user_assertion="user-jwt",
        scopes=["https://api.fabric.microsoft.com/.default"],
    )
    set_user_assertion(None)  # cleanup


async def test_client_credentials_fallback() -> None:
    """Client credentials used when no user assertion."""
    from src.auth import PowerBITokenManager, set_user_assertion

    tm = PowerBITokenManager()
    mock_app = MagicMock()
    mock_app.acquire_token_for_client.return_value = {"access_token": "cc-token"}
    tm._app = mock_app

    set_user_assertion(None)
    token = await tm.get_token()

    assert token == "cc-token"
    mock_app.acquire_token_for_client.assert_called_once()
    mock_app.acquire_token_on_behalf_of.assert_not_called()


async def test_obo_token_failure() -> None:
    """OBO failure raises RuntimeError with details."""
    from src.auth import PowerBITokenManager, set_user_assertion

    tm = PowerBITokenManager()
    mock_app = MagicMock()
    mock_app.acquire_token_on_behalf_of.return_value = {
        "error": "invalid_grant",
        "error_description": "token expired",
    }
    tm._app = mock_app

    set_user_assertion("expired-jwt")
    with pytest.raises(RuntimeError, match="OBO token exchange failed.*token expired"):
        await tm.get_token()
    set_user_assertion(None)


# --- Auth: auth provider creation ---


def test_auth_provider_none_mode() -> None:
    """No auth provider when AUTH_MODE=none."""
    with patch("src.server.settings") as mock_settings:
        from src.config import AuthMode
        mock_settings.AUTH_MODE = AuthMode.NONE
        from src.server import _create_auth
        assert _create_auth() is None


def test_auth_provider_obo_requires_base_url() -> None:
    """OBO mode raises ValueError without MCP_BASE_URL."""
    with patch("src.server.settings") as mock_settings:
        from src.config import AuthMode
        mock_settings.AUTH_MODE = AuthMode.OBO
        mock_settings.MCP_BASE_URL = ""
        from src.server import _create_auth
        with pytest.raises(ValueError, match="MCP_BASE_URL is required"):
            _create_auth()
