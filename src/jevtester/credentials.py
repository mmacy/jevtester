"""Credentials for hosted targets, read from the signed-in CLIs.

A credential is read in code and used there. Nothing here prints, logs, or returns a token outside the provider
that sends it.
"""

import asyncio
import time
from collections.abc import Callable
from typing import Protocol

from azure.core.credentials import AccessToken
from azure.identity.aio import AzureCliCredential

COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
REFRESH_MARGIN_S = 300.0
"""Get a new token this many seconds before the current one expires."""


class CredentialError(Exception):
    """A credential couldn't be read. The message says what to do, like `Run az login`."""


class AsyncTokenCredential(Protocol):
    """The part of an `azure-identity` async credential that jevtester uses."""

    async def get_token(self, *scopes: str) -> AccessToken:
        """Return a token for the scopes."""
        ...


class TokenSource(Protocol):
    """A bearer token that a provider sends, and a description of where it comes from."""

    async def token(self) -> str:
        """Return a token that's valid for at least a few more minutes.

        Raises:
            CredentialError: No token can be read.
        """
        ...

    def describe(self) -> str | None:
        """Describe the source and when it refreshes, like `Azure CLI, refreshes in 41 min`.

        Returns:
            The description, or `None` before the first token is read.
        """
        ...


class AzureCliToken:
    """An Entra ID token from the `az` sign-in, cached until shortly before it expires."""

    def __init__(
        self,
        scope: str = COGNITIVE_SERVICES_SCOPE,
        credential: AsyncTokenCredential | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Read tokens for `scope`.

        Args:
            scope: The token scope. Foundry uses the Cognitive Services scope.
            credential: The credential to read tokens from. `None` uses the `az` CLI sign-in.
            clock: The current Unix time, for tests.
        """
        self._scope = scope
        self._credential: AsyncTokenCredential = credential or AzureCliCredential()
        self._clock = clock
        self._cached: AccessToken | None = None
        self._lock = asyncio.Lock()

    async def token(self) -> str:
        """Return the cached token, or read a new one when it's within five minutes of expiring.

        Raises:
            CredentialError: The `az` CLI isn't signed in, or can't be run.
        """
        async with self._lock:
            if self._cached is None or self._cached.expires_on - self._clock() < REFRESH_MARGIN_S:
                try:
                    self._cached = await self._credential.get_token(self._scope)
                except Exception as error:
                    raise CredentialError("The Azure CLI sign-in failed. Run az login.") from error
            return self._cached.token

    def describe(self) -> str | None:
        """Describe the token's source and when it refreshes."""
        if self._cached is None:
            return None
        minutes = max(0, round((self._cached.expires_on - REFRESH_MARGIN_S - self._clock()) / 60))
        return f"Azure CLI, refreshes in {minutes} min"
