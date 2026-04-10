import os
from enum import Enum

from loguru import logger
from pydantic_settings import BaseSettings, SettingsConfigDict

logger.remove()
logger.add(
    sink=lambda msg: print(msg, end=""),
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="{time:DD-MM-YYYY at HH:mm:ss} | {level: <8} | {message}",
)


class TransportType(str, Enum):
    STDIO = "stdio"
    HTTP = "http"


class Settings(BaseSettings):
    # Azure AD (Service Principal)
    TENANT_ID: str = ""
    CLIENT_ID: str = ""
    CLIENT_SECRET: str = ""

    # MCP Server
    MCP_TRANSPORT: TransportType = TransportType.HTTP
    MCP_PORT: int = 2009

    # Application
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
