import atexit

from src.config import settings
from src.powerbi import powerbi_client
from src.server import mcp


def _shutdown() -> None:
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(powerbi_client.close())
        else:
            loop.run_until_complete(powerbi_client.close())
    except Exception:
        pass


atexit.register(_shutdown)


def main():
    if settings.MCP_TRANSPORT == "http":
        mcp.run(transport="http", host="0.0.0.0", port=settings.MCP_PORT, path="/mcp")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
