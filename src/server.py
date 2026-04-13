import traceback
from typing import Any, Optional

from fastmcp import FastMCP
from loguru import logger
from pydantic import AnyHttpUrl

from .auth import set_user_assertion
from .config import AuthMode, settings
from .powerbi import powerbi_client


def _create_auth():
    """Create auth provider for OBO mode, or None for no auth."""
    if settings.AUTH_MODE != AuthMode.OBO:
        return None
    if not settings.MCP_BASE_URL:
        raise ValueError("MCP_BASE_URL is required when AUTH_MODE=obo")

    from fastmcp.server.auth import MultiAuth, RemoteAuthProvider
    from fastmcp.server.auth.providers.azure import AzureJWTVerifier
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    tid = settings.TENANT_ID
    cid = settings.CLIENT_ID
    audience = [cid, f"api://{cid}"]

    # v2.0 verifier (Copilot Studio, modern clients)
    v2_verifier = AzureJWTVerifier(
        client_id=cid,
        tenant_id=tid,
        required_scopes=["access_as_user"],
    )

    # v1.0 verifier (Azure CLI, legacy clients issue v1.0 tokens)
    v1_verifier = JWTVerifier(
        jwks_uri=f"https://login.microsoftonline.com/{tid}/discovery/v2.0/keys",
        issuer=f"https://sts.windows.net/{tid}/",
        audience=audience,
        algorithm="RS256",
        required_scopes=["access_as_user"],
    )

    # RemoteAuthProvider handles routes + v2 validation, MultiAuth adds v1 fallback
    v2_remote = RemoteAuthProvider(
        token_verifier=v2_verifier,
        authorization_servers=[
            AnyHttpUrl(f"https://login.microsoftonline.com/{tid}/v2.0"),
        ],
        base_url=settings.MCP_BASE_URL,
    )
    return MultiAuth(server=v2_remote, verifiers=[v1_verifier])


mcp = FastMCP("Power BI - Semantic Model Query Server", auth=_create_auth())


def _apply_user_assertion() -> None:
    """Extract the user's bearer token from the request context for OBO exchange."""
    if settings.AUTH_MODE != AuthMode.OBO:
        set_user_assertion(None)
        return
    try:
        from fastmcp.server.dependencies import get_access_token

        token = get_access_token()
        if token:
            logger.info("OBO: user assertion set (token present)")
        else:
            logger.warning("OBO: no access token in request context, falling back to client credentials")
        set_user_assertion(token.token if token else None)
    except RuntimeError:
        logger.warning("OBO: failed to get access token, falling back to client credentials")
        set_user_assertion(None)


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
        _apply_user_assertion()
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
        _apply_user_assertion()
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
        _apply_user_assertion()
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
        _apply_user_assertion()
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
        _apply_user_assertion()
        return await powerbi_client.list_reports(workspace_id)
    except Exception as e:
        logger.error(f"List reports failed: {e}\n{traceback.format_exc()}")
        return {"error": str(e)}
