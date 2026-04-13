import base64
import os
import subprocess
import tempfile
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


_cert_tempfile: str | None = None


def _decode_cert_base64(b64: str) -> str:
    """Decode a base64-encoded PFX certificate to a temp file. Returns the path."""
    global _cert_tempfile
    if _cert_tempfile and Path(_cert_tempfile).exists():
        return _cert_tempfile
    data = base64.b64decode(b64)
    fd, path = tempfile.mkstemp(suffix=".pfx")
    os.write(fd, data)
    os.close(fd)
    _cert_tempfile = path
    logger.info("Decoded CLIENT_CERT_BASE64 to {}", path)
    return path


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

    # Certificate auth (required — provide path OR base64)
    CLIENT_CERT_PATH: str = ""
    CLIENT_CERT_BASE64: str = ""
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
    def client_credential(self) -> dict[str, str]:
        """Return MSAL client credential: certificate dict."""
        cert_path = self.CLIENT_CERT_PATH
        if not cert_path and self.CLIENT_CERT_BASE64:
            cert_path = _decode_cert_base64(self.CLIENT_CERT_BASE64)
        if not cert_path:
            raise ValueError("CLIENT_CERT_PATH or CLIENT_CERT_BASE64 must be set.")
        cred: dict[str, str] = {"private_key_pfx_path": cert_path}
        if self.CLIENT_CERT_PASSPHRASE:
            cred["passphrase"] = self.CLIENT_CERT_PASSPHRASE
        return cred

    model_config = SettingsConfigDict(
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
