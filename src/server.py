import traceback
from typing import Any, Optional

from fastmcp import FastMCP
from loguru import logger

from .powerbi import powerbi_client

mcp = FastMCP("Power BI - Semantic Model Query Server")


@mcp.tool()
async def get_semantic_model_schema(
    dataset_id: str, workspace_id: Optional[str] = None,
) -> dict[str, Any]:
    """Retrieve the full schema of a Power BI semantic model.

    Returns tables, columns (with data types), measures (with DAX expressions),
    and relationships. Use this to understand the model structure before writing
    DAX queries.

    Provide workspace_id to skip auto-detection (faster).
    """
    try:
        return await powerbi_client.get_semantic_model_schema(dataset_id, workspace_id)
    except Exception as e:
        logger.error(f"Schema retrieval failed: {e}\n{traceback.format_exc()}")
        return {"error": str(e)}


@mcp.tool()
async def execute_dax_query(dataset_id: str, dax_query: str) -> dict[str, Any]:
    """Execute a DAX query against a Power BI semantic model and return results.

    Returns column names and rows. Use get_semantic_model_schema first to
    understand the model, then write a DAX query to execute here.
    """
    try:
        return await powerbi_client.execute_dax(dataset_id, dax_query)
    except Exception as e:
        logger.error(f"Query execution failed: {e}\n{traceback.format_exc()}")
        return {"error": str(e)}


@mcp.tool()
async def list_workspaces() -> dict[str, Any]:
    """List all Power BI workspaces accessible to the service principal.

    Use this as a starting point to discover available datasets and reports.
    """
    try:
        return await powerbi_client.list_workspaces()
    except Exception as e:
        logger.error(f"List workspaces failed: {e}\n{traceback.format_exc()}")
        return {"error": str(e)}


@mcp.tool()
async def list_datasets(workspace_id: Optional[str] = None) -> dict[str, Any]:
    """List datasets (semantic models) in a Power BI workspace.

    Omit workspace_id to list datasets across all accessible workspaces.
    Provide workspace_id to list datasets in a specific workspace (faster).
    """
    try:
        return await powerbi_client.list_datasets(workspace_id)
    except Exception as e:
        logger.error(f"List datasets failed: {e}\n{traceback.format_exc()}")
        return {"error": str(e)}


@mcp.tool()
async def list_reports(workspace_id: Optional[str] = None) -> dict[str, Any]:
    """List reports in a Power BI workspace.

    Omit workspace_id to list reports across all accessible workspaces.
    Provide workspace_id to list reports in a specific workspace (faster).
    """
    try:
        return await powerbi_client.list_reports(workspace_id)
    except Exception as e:
        logger.error(f"List reports failed: {e}\n{traceback.format_exc()}")
        return {"error": str(e)}
