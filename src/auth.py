import asyncio

import msal
from loguru import logger

from .config import settings

POWER_BI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"


class PowerBITokenManager:
    def __init__(self) -> None:
        self._app: msal.ConfidentialClientApplication | None = None

    def _get_app(self) -> msal.ConfidentialClientApplication:
        if self._app is None:
            authority = f"https://login.microsoftonline.com/{settings.TENANT_ID}"
            self._app = msal.ConfidentialClientApplication(
                settings.CLIENT_ID,
                authority=authority,
                client_credential=settings.CLIENT_SECRET,
            )
        return self._app

    async def get_token(self) -> str:
        app = self._get_app()
        result = await asyncio.to_thread(
            app.acquire_token_for_client, scopes=[POWER_BI_SCOPE]
        )

        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "Unknown error"))
            raise RuntimeError(f"Power BI token acquisition failed: {error}")

        logger.debug("Power BI token acquired")
        return result["access_token"]


token_manager = PowerBITokenManager()
