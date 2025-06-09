# Copyright (c) 2025, WSO2 LLC. (https://www.wso2.com/) All Rights Reserved.

# WSO2 LLC. licenses this file to you under the Apache License,
# Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.
# You may obtain postgres_pgvector copy of the License at

# http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied. See the License for the
# specific language governing permissions and limitations
# under the License.

from http.client import HTTPException
import anyio
import httpx
import logging
import secrets
import time

from collections.abc import Awaitable, Callable
from typing import Dict, Protocol
from urllib.parse import urlencode

from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
)

from oauth.types import OAuthMetadata, OAuthToken, TokenStorage
from oauth.common import (
    discover_oauth_metadata,
    is_token_expired,
    get_endpoint,
    generate_code_verifier,
    generate_code_challenge,
)
from mcp.shared._httpx_utils import create_mcp_http_client

logger = logging.getLogger(__name__)


class FHIRClientProvider(httpx.Auth):
    """
    Authentication for httpx using anyio.
    Handles OAuth flow and token storage.
    """

    def __init__(
        self,
        discovery_url: str,
        client_metadata: OAuthClientMetadata,
        storage: TokenStorage,
        redirect_handler: Callable[[str], Awaitable[None]],
        timeout: float = 300.0,
    ):
        """
        Initialize OAuth2 authentication.

        Args:
            discovery_url: Discovery URL of the server capabilities
            client_metadata: OAuth client metadata
            storage: Token storage implementation (defaults to in-memory)
            redirect_handler: Function to handle authorization URL like opening browser
            callback_handler: Function to wait for callback and return (auth_code, state)
            timeout: Timeout for OAuth flow in seconds
        """
        self.discovery_url = discovery_url
        self.client_metadata = client_metadata
        self.storage = storage
        self.redirect_handler = redirect_handler
        self.timeout = timeout

        # Cached authentication state
        self._metadata: OAuthMetadata | None = None

        # Thread safety lock
        self._token_lock = anyio.Lock()
        self._state_mapping: dict[str, dict[str, str]] = {}

    def _generate_code_verifier(self) -> str:
        """Generate a cryptographically random code verifier for PKCE."""
        return generate_code_verifier(128)

    def _generate_code_challenge(self, code_verifier: str) -> str:
        """Generate a code challenge from a code verifier using SHA256."""
        return generate_code_challenge(code_verifier)

    async def _discover_oauth_metadata(
        self, discovery_url: str
    ) -> OAuthMetadata | None:
        """
        Discover OAuth metadata from server's well-known endpoint.
        """

        return await discover_oauth_metadata(
            metadata_url=discovery_url, headers={"Accept": "application/fhir+json"}
        )

    def _is_valid_token(self, token_id: str) -> bool:
        """Check if current token is valid."""
        current_token: OAuthToken | None = self.storage.get_token(token_id)
        return not is_token_expired(current_token)

    async def _validate_token_scopes(self, token_response: OAuthToken) -> None:
        """
        Validate returned scopes against requested scopes.

        Per OAuth 2.1 Section 3.3: server may grant subset, not superset.
        """
        if not token_response.scope:
            # No scope returned = validation passes
            return

        # Check explicitly requested scopes only
        requested_scopes: set[str] = set()

        if self.client_metadata.scope:
            # Validate against explicit scope request
            requested_scopes = set(self.client_metadata.scope.split())

            # Check for unauthorized scopes
            returned_scopes = set(token_response.scope.split())
            unauthorized_scopes = returned_scopes - requested_scopes

            if unauthorized_scopes:
                raise Exception(
                    f"Server granted unauthorized scopes: {unauthorized_scopes}. "
                    f"Requested: {requested_scopes}, Returned: {returned_scopes}"
                )
        else:
            # No explicit scopes requested - accept server defaults
            logger.debug(
                f"No explicit scopes requested, accepting server-granted "
                f"scopes: {set(token_response.scope.split())}"
            )

    async def _get_client_info(self) -> OAuthClientInformationFull:
        """Get the client info."""

        client_info: OAuthClientInformationFull | None = self.storage.get_client_info()

        if not client_info:
            raise Exception("No client information available")
        return client_info

    async def ensure_token(self, token_id: str) -> None:
        """Ensure valid access token, refreshing or re-authenticating as needed."""
        async with self._token_lock:
            # Return early if token is valid
            if self._is_valid_token(token_id):
                return

            # Try refreshing existing token
            if await self._refresh_access_token(token_id):
                return

            # Fall back to full OAuth flow
            await self._perform_oauth_flow(token_id)

    async def _perform_oauth_flow(self, token_id: str) -> None:
        """Execute OAuth2 authorization code flow with PKCE."""
        logger.debug("Starting authentication flow.")

        # Discover OAuth metadata
        if not self._metadata:
            self._metadata = await self._discover_oauth_metadata(self.discovery_url)

        # Ensure client registration
        client_info: OAuthClientInformationFull = await self._get_client_info()

        # Generate PKCE challenge
        code_verifier: str = self._generate_code_verifier()
        code_challenge: str = self._generate_code_challenge(code_verifier)

        authorization_endpoint: str = self._get_authorization_endpoint()

        # Build authorization URL
        state: str = secrets.token_urlsafe(32)
        auth_params: Dict[str, str] = {
            "response_type": "code",
            "client_id": client_info.client_id,
            "redirect_uri": str(self.client_metadata.redirect_uris[0]),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        # Include explicit scopes only
        if self.client_metadata.scope:
            auth_params["scope"] = self.client_metadata.scope

        auth_url: str = f"{authorization_endpoint}?{urlencode(auth_params)}"

        self._state_mapping[state] = {
            **auth_params,
            "token_id": token_id,
            "code_verifier": code_verifier,
        }

        # Redirect user for authorization
        await self.redirect_handler(auth_url)

    async def handle_fhir_oauth_callback(self, code: str, state: str) -> None:

        state_mapping: Dict[str, str] | None = self._state_mapping.get(state)
        if not state_mapping:
            raise HTTPException(400, "Invalid state parameter")

        code_verifier: str = state_mapping["code_verifier"]
        token_id: str = state_mapping["token_id"]

        # Exchange authorization code for tokens
        await self._exchange_code_for_token(token_id, code, code_verifier)

    async def _exchange_code_for_token(
        self,
        token_id: str,
        auth_code: str,
        code_verifier: str,
    ) -> None:
        """Exchange authorization code for access token."""
        token_endpoint: str = self._get_token_endpoint()

        client_info: OAuthClientInformationFull = await self._get_client_info()

        token_payload: dict = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": str(self.client_metadata.redirect_uris[0]),
            "client_id": client_info.client_id,
            "code_verifier": code_verifier,
        }

        if client_info.client_secret:
            token_payload["client_secret"] = client_info.client_secret

        async with create_mcp_http_client() as client:
            response = await client.post(
                url=token_endpoint,
                data=token_payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0,
            )

            if response.status_code != 200:
                # Parse OAuth error response
                try:
                    error_data = response.json()
                    error_msg = error_data.get(
                        "error_description",
                        error_data.get("error", "Token generation failed"),
                    )
                    raise Exception(
                        f"Token exchange failed: {error_msg} "
                        f"(HTTP {response.status_code})"
                    )
                except Exception:
                    raise Exception(
                        f"Token exchange failed: {response.status_code} {response.text}"
                    )

            # Parse token response
            token_response: OAuthToken = OAuthToken.model_validate(response.json())

            # Validate token scopes
            await self._validate_token_scopes(token_response)

            # Calculate token expiry
            if not token_response.expires_at:
                if token_response.expires_in:
                    token_response.expires_at = time.time() + token_response.expires_in
                else:
                    token_response.expires_at = time.time() + 3600

            # Store tokens
            self.storage.set_token(token_id, token_response)

    def _get_authorization_endpoint(self) -> str:
        """Get authorization endpoint."""
        return get_endpoint(self._metadata, "authorization_endpoint")

    def _get_token_endpoint(self) -> str:
        """Get token endpoint."""
        return get_endpoint(self._metadata, "token_endpoint")

    async def _refresh_access_token(self, token_id: str) -> bool:
        """Refresh access token using refresh token."""

        current_token: OAuthToken | None = self.storage.get_token(token_id)

        if not current_token:
            return False

        token_endpoint: str = self._get_token_endpoint()

        # Get client credentials
        client_info: OAuthClientInformationFull = await self._get_client_info()

        refresh_token_payload = {
            "grant_type": "refresh_token",
            "refresh_token": current_token.refresh_token,
            "client_id": client_info.client_id,
            "client_secret": client_info.client_secret,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url=token_endpoint,
                    data=refresh_token_payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=30.0,
                )

                if response.status_code != 200:
                    logger.error(f"Token refresh failed: {response.status_code}")
                    return False

                # Parse refreshed tokens
                token_response: OAuthToken = OAuthToken.model_validate(response.json())

                # Validate token scopes
                await self._validate_token_scopes(token_response)

                # Calculate token expiry
                if not token_response.expires_at:
                    if token_response.expires_in:
                        token_response.expires_at = (
                            time.time() + token_response.expires_in
                        )
                    else:
                        token_response.expires_at = time.time() + 3600

                # Store refreshed tokens
                self.storage.set_token(token_id, token_response)

                return True

        except Exception as ex:
            logger.exception("Token refresh failed. Caused by, ", ex)
            return False

    async def get_access_token(self, token_id: str) -> OAuthToken | None:
        """Get access token for the given token ID."""
        await self.ensure_token(token_id)
        return self.storage.get_token(token_id)
