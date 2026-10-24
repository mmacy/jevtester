"""The provider for every server that speaks the System One API: Foundry, Ollama, and the MLX server."""

from typing import Any

import httpx2
from typesafe_sdk import AsyncTypeSafeClient

from jevtester.credentials import CredentialError, TokenSource
from jevtester.normalize import ResultError
from jevtester.providers.base import Health, RawResult
from jevtester.providers.typesafe import make_client, system_one
from jevtester.spec import Capabilities, DecisionRequest, Target

HEALTH_TIMEOUT_S = 3.0


class SystemOneProvider:
    """A System One server, reached through the TypeSafe SDK."""

    def __init__(
        self,
        target: Target,
        credential: TokenSource | None = None,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """Connect to one target.

        Args:
            target: The target. It must have a `base_url`.
            credential: Where the bearer token comes from. `None` sends no real token.
            transport: An HTTP transport to use instead of the network, for tests.

        Raises:
            ValueError: The target has no `base_url`.
        """
        if target.base_url is None:
            raise ValueError(f"{target.name} has no base_url.")
        self.target = target
        self.capabilities: Capabilities = target.capabilities
        self._base_url = target.base_url
        self._credential = credential
        self._transport = transport
        self._client: AsyncTypeSafeClient | None = None
        self._client_key: str | None = None

    def _client_for(self, key: str | None) -> AsyncTypeSafeClient:
        # The SDK fixes the key when a client is built, so a refreshed token needs a new client.
        if self._client is None or key != self._client_key:
            self._client = make_client(self._base_url, key, transport=self._transport)
            self._client_key = key
        return self._client

    def request_body(self, request: DecisionRequest) -> dict[str, Any]:
        """Build the body this target is sent.

        Args:
            request: The state and questions.

        Returns:
            The System One body, with `truncate` when the target sets it.
        """
        extra = {"truncate": self.target.truncate} if self.target.truncate is not None else None
        return request.system_one_body(self.target.model, extra=extra)

    async def decide(self, request: DecisionRequest, *, timeout: float) -> RawResult:
        """Send one request.

        Args:
            request: The state and questions to send.
            timeout: Seconds to wait, including retries.

        Returns:
            The request and response bodies and the latency, or an error.
        """
        body = self.request_body(request)
        if request.images:
            # The SDK sends images as named assets, and the Clef servers expect another format.
            return RawResult(
                request_body=body,
                error=ResultError(code="preflight", message="Images aren't supported on System One targets yet."),
            )
        try:
            key = await self._credential.token() if self._credential else None
        except CredentialError as error:
            return RawResult(request_body=body, error=ResultError(code="auth", message=str(error)))
        return await system_one(self._client_for(key), body, timeout=timeout)

    async def health_check(self) -> Health:
        """Check that a credential can be read, or for a server without one, that it's listening.

        Returns:
            Ready when the check passes, with the credential's source.
        """
        if self._credential is None:
            return await self._check_listening()
        try:
            await self._credential.token()
        except CredentialError as error:
            return Health(reason="Can't get a token", detail=str(error))
        return Health(credential=self._credential.describe())

    async def _check_listening(self) -> Health:
        try:
            async with httpx2.AsyncClient(transport=self._transport, timeout=HEALTH_TIMEOUT_S) as client:
                await client.get(self._base_url)
        except httpx2.HTTPError:
            return Health(reason="The server isn't running", detail=f"Nothing answers at {self._base_url}")
        return Health()
