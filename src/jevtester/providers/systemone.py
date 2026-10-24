"""The provider for every server that speaks the System One API: Foundry, Ollama, and the MLX server."""

from typing import Any, cast

import httpx2
from typesafe_sdk import AsyncTypeSafeClient

from jevtester.credentials import CredentialError, TokenSource
from jevtester.normalize import ResultError
from jevtester.providers.base import Health, RawResult
from jevtester.providers.typesafe import make_client, system_one
from jevtester.spec import Capabilities, DecisionRequest, Target

HEALTH_TIMEOUT_S = 3.0
OLLAMA_MIN_VERSION = (0, 35, 1)
"""The first Ollama release that serves Clef-flash."""


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
        if request.images:
            # The SDK sends images as named assets, and the Clef servers expect another format.
            return RawResult(
                request_body=None,
                error=ResultError(code="preflight", message="Images aren't supported on System One targets yet."),
            )
        if self.target.runtime == "mlx":
            # The MLX server answers with whatever model it loaded, whatever the request names.
            health = await self._check_mlx()
            if health.reason:
                return RawResult(request_body=None, error=ResultError(code="not_ready", message=health.reason))
        try:
            key = await self._credential.token() if self._credential else None
        except CredentialError as error:
            return RawResult(request_body=None, error=ResultError(code="auth", message=str(error)))
        return await system_one(self._client_for(key), self.request_body(request), timeout=timeout)

    async def health_check(self) -> Health:
        """Check that the target can take a request.

        Foundry needs a token. Ollama must be recent enough and have the model pulled. The MLX server must have the
        target's model loaded. Any other server must answer at its base URL.

        Returns:
            Ready when the check passes, with the credential's source.
        """
        match self.target.runtime:
            case "ollama":
                return await self._check_ollama()
            case "mlx":
                return await self._check_mlx()
            case _ if self._credential is not None:
                try:
                    await self._credential.token()
                except CredentialError as error:
                    return Health(reason="Can't get a token", detail=str(error))
                return Health(credential=self._credential.describe())
            case _:
                return await self._check_listening()

    async def _get_json(self, path: str) -> Any:
        async with httpx2.AsyncClient(transport=self._transport, timeout=HEALTH_TIMEOUT_S) as client:
            response = await client.get(f"{self._base_url}{path}")
            response.raise_for_status()
            return response.json()

    async def _check_listening(self) -> Health:
        try:
            async with httpx2.AsyncClient(transport=self._transport, timeout=HEALTH_TIMEOUT_S) as client:
                await client.get(self._base_url)
        except httpx2.HTTPError:
            return Health(reason="The server isn't running", detail=f"Nothing answers at {self._base_url}")
        return Health()

    async def _check_ollama(self) -> Health:
        model = self.target.model
        try:
            version = str(cast(dict[str, Any], await self._get_json("/api/version")).get("version", ""))
            tags: list[Any] = cast(dict[str, Any], await self._get_json("/api/tags")).get("models") or []
        except httpx2.HTTPError, ValueError, AttributeError:
            return Health(reason="Ollama isn't running", detail=f"Start it with ollama serve ({self._base_url})")
        if _version_tuple(version) < OLLAMA_MIN_VERSION:
            minimum = ".".join(str(part) for part in OLLAMA_MIN_VERSION)
            return Health(reason="Ollama is too old", detail=f"Needs {minimum} or later, found {version or 'unknown'}")
        names = {str(cast(dict[str, Any], tag).get("name", "")) for tag in tags}
        if model not in names and f"{model}:latest" not in names:
            return Health(reason=f"{model} isn't pulled", detail=f"Run ollama pull {model}")
        return Health(detail=f"Ollama {version}")

    async def _check_mlx(self) -> Health:
        try:
            loaded = cast(dict[str, Any], await self._get_json("/health")).get("model")
        except httpx2.HTTPError, ValueError, AttributeError:
            return Health(
                reason="The MLX server isn't running",
                detail=f"Start python clef_mlx.py serve --no-truncate in ~/models/clef-mlx/{self.target.model}",
            )
        if not isinstance(loaded, str) or not loaded:
            return Health(
                reason="The MLX server doesn't name its model", detail="Restart it with a current clef_mlx.py"
            )
        if loaded != self.target.model:
            return Health(
                reason=f"The MLX server has {loaded} loaded",
                detail=f"Restart it from ~/models/clef-mlx/{self.target.model}",
            )
        return Health()


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in version.split("."):
        digits = "".join(character for character in part if character.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)
