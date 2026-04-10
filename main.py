from src.config import settings
from src.server import mcp


def main():
    if settings.MCP_TRANSPORT == "http":
        mcp.run(transport="http", host="0.0.0.0", port=settings.MCP_PORT, path="/mcp")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
