import asyncio
from contextvars import ContextVar

import msal
from loguru import logger

from .config import settings

POWER_BI_SCOPE = "https://api.fabric.microsoft.com/.default"

_user_assertion: ContextVar[str | None] = ContextVar("_user_assertion", default=None)


def set_user_assertion(assertion: str | None) -> None:
    """Set the user assertion token for OBO exchange in the current context."""
    _user_assertion.set(assertion)


class PowerBITokenManager:
    def __init__(self) -> None:
        self._app: msal.ConfidentialClientApplication | None = None

    def _get_app(self) -> msal.ConfidentialClientApplication:
        if self._app is None:
            authority = f"https://login.microsoftonline.com/{settings.TENANT_ID}"
            self._app = msal.ConfidentialClientApplication(
                settings.CLIENT_ID,
                authority=authority,
                client_credential=settings.client_credential,
            )
        return self._app

    async def get_token(self) -> str:
        """Get a Power BI token. Uses OBO if a user assertion is set, otherwise client credentials."""
        assertion = _user_assertion.get()
        if assertion:
            return await self._get_token_obo(assertion)
        return await self._get_token_client_credentials()

    async def _get_token_client_credentials(self) -> str:
        app = self._get_app()
        result = await asyncio.to_thread(
            app.acquire_token_for_client, scopes=[POWER_BI_SCOPE]
        )

        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "Unknown error"))
            raise RuntimeError(f"Power BI token acquisition failed: {error}")

        logger.debug("Power BI token acquired (client credentials)")
        return result["access_token"]

    async def _get_token_obo(self, user_assertion: str) -> str:
        app = self._get_app()
        result = await asyncio.to_thread(
            app.acquire_token_on_behalf_of,
            user_assertion=user_assertion,
            scopes=[POWER_BI_SCOPE],
        )

        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "Unknown error"))
            raise RuntimeError(f"OBO token exchange failed: {error}")

        logger.debug("Power BI token acquired (OBO)")
        return result["access_token"]


token_manager = PowerBITokenManager()
