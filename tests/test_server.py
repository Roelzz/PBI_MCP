import base64
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
    mock_client.post.return_value = mock_resp
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
    mock_client.post.return_value = mock_resp
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
    mock_client.post.return_value = mock_resp
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
    mock_client.post.return_value = mock_resp
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
