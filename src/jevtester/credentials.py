"""Credentials for hosted targets, read from the signed-in CLIs.

A credential is read in code and used there. Nothing here prints, logs, or returns a token outside the provider
that sends it.
"""

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, cast

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

    def invalidate(self) -> None:
        """Forget the cached token, after a server rejects it."""
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

    def invalidate(self) -> None:
        """Forget the cached token."""
        self._cached = None


CLOUDFLARE_TOKEN_ENV = "CLOUDFLARE_API_TOKEN"
WRANGLER_COMMAND = ("npx", "--no-install", "wrangler", "auth", "token", "--json")
"""Prints the Wrangler sign-in's current token. `--no-install` keeps npx from downloading Wrangler."""
WRANGLER_TOKEN_TTL_S = 600.0
"""Wrangler doesn't say when its token expires, so jevtester asks again after this long, or after a 401."""
WRANGLER_TIMEOUT_S = 60.0

type Runner = Callable[[], Awaitable[tuple[int, bytes]]]
"""Runs the Wrangler command and returns its exit code and stdout."""


async def _run_wrangler() -> tuple[int, bytes]:
    process = await asyncio.create_subprocess_exec(
        *WRANGLER_COMMAND, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    stdout, _ = await asyncio.wait_for(process.communicate(), WRANGLER_TIMEOUT_S)
    return process.returncode or 0, stdout


class WranglerToken:
    """A Cloudflare token from `CLOUDFLARE_API_TOKEN`, or else from the Wrangler sign-in."""

    def __init__(
        self,
        run: Runner = _run_wrangler,
        environ: Mapping[str, str] = os.environ,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Read tokens from the environment or Wrangler.

        Args:
            run: Runs the Wrangler command, for tests.
            environ: The environment to read `CLOUDFLARE_API_TOKEN` from.
            clock: A monotonic clock in seconds, for tests.
        """
        self._run = run
        self._environ = environ
        self._clock = clock
        self._cached: tuple[str, float] | None = None
        self._lock = asyncio.Lock()

    async def token(self) -> str:
        """Return `CLOUDFLARE_API_TOKEN`, or the Wrangler sign-in's token, read again every 10 minutes.

        Raises:
            CredentialError: Wrangler isn't signed in, or can't be run.
        """
        if from_env := self._environ.get(CLOUDFLARE_TOKEN_ENV, "").strip():
            return from_env
        async with self._lock:
            if self._cached is None or self._clock() - self._cached[1] > WRANGLER_TOKEN_TTL_S:
                self._cached = (await self._read_wrangler(), self._clock())
            return self._cached[0]

    async def _read_wrangler(self) -> str:
        try:
            code, stdout = await self._run()
        except (OSError, TimeoutError) as error:
            raise CredentialError("Wrangler can't be run. Install it with npm install --global wrangler.") from error
        token: object = None
        if code == 0:
            try:
                token = cast(dict[str, object], json.loads(stdout)).get("token")
            except ValueError, AttributeError:
                token = None
        if not isinstance(token, str) or not token:
            raise CredentialError("The Wrangler sign-in failed. Run npx wrangler login.")
        return token

    def describe(self) -> str | None:
        """Describe where the token comes from."""
        if self._environ.get(CLOUDFLARE_TOKEN_ENV, "").strip():
            return CLOUDFLARE_TOKEN_ENV
        return "Wrangler sign-in" if self._cached is not None else None

    def invalidate(self) -> None:
        """Forget the cached Wrangler token."""
        self._cached = None
