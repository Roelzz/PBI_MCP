import os
import subprocess
from enum import Enum
from pathlib import Path

from loguru import logger
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> str:
    """Resolve .env from the main git working tree so worktrees share one .env."""
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        env_path = Path(root).parent / ".env"
        if env_path.is_file():
            return str(env_path)
    except (subprocess.CalledProcessError, OSError):
        pass
    return ".env"

logger.remove()
logger.add(
    sink=lambda msg: print(msg, end=""),
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="{time:DD-MM-YYYY at HH:mm:ss} | {level: <8} | {message}",
)


class TransportType(str, Enum):
    STDIO = "stdio"
    HTTP = "http"


class AuthMode(str, Enum):
    NONE = "none"
    OBO = "obo"


class Settings(BaseSettings):
    # Azure AD (Service Principal)
    TENANT_ID: str = ""
    CLIENT_ID: str = ""
    CLIENT_SECRET: str = ""

    # Certificate auth (preferred over client secret)
    CLIENT_CERT_PATH: str = ""
    CLIENT_CERT_PASSPHRASE: str = ""

    # Auth mode: "none" (client credentials) or "obo" (Azure AD JWT + OBO)
    AUTH_MODE: AuthMode = AuthMode.NONE
    MCP_BASE_URL: str = ""

    # MCP Server
    MCP_TRANSPORT: TransportType = TransportType.HTTP
    MCP_PORT: int = 2009

    # Application
    LOG_LEVEL: str = "INFO"

    @property
    def client_credential(self) -> str | dict[str, str]:
        """Return MSAL client credential: certificate dict or secret string."""
        if self.CLIENT_CERT_PATH:
            cred: dict[str, str] = {"private_key_pfx_path": self.CLIENT_CERT_PATH}
            if self.CLIENT_CERT_PASSPHRASE:
                cred["passphrase"] = self.CLIENT_CERT_PASSPHRASE
            return cred
        if self.CLIENT_SECRET:
            return self.CLIENT_SECRET
        raise ValueError(
            "Either CLIENT_CERT_PATH or CLIENT_SECRET must be set."
        )

    model_config = SettingsConfigDict(
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
