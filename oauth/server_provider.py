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

import logging
import secrets
import time

from pydantic import AnyHttpUrl
from starlette.exceptions import HTTPException

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    AuthorizationParams,
    construct_redirect_uri,
)
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from oauth.common import (
    discover_oauth_metadata,
    get_endpoint,
    generate_code_challenge,
    generate_code_verifier,
)
from oauth.types import OAuthMetadata, ServerConfigs

logger = logging.getLogger(__name__)


class OAuthServerProvider(OAuthAuthorizationServerProvider):

    def __init__(self, configs: ServerConfigs):
        self.configs = configs

        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self.tokens: dict[str, AccessToken] = {}
        self.state_mapping: dict[str, dict[str, str]] = {}
        self.token_mapping: dict[str, str] = {}

        self._metadata: OAuthMetadata | None = None

    async def initialize(self) -> None:
        """Initialize the OAuth server."""
        self._metadata = await self._discover_oauth_metadata()

    #
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Get OAuth client information."""
        return self.clients.get(client_id)

    #
    async def register_client(self, client_info: OAuthClientInformationFull):
        """Register a new OAuth client."""
        self.clients[client_info.client_id] = client_info

    #
    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Generate an authorization URL for OAuth flow."""

        # Discover OAuth metadata
        if not self._metadata:
            self._metadata = await self._discover_oauth_metadata()

        authorization_endpoint: str = await self._get_authorization_endpoint()

        state: str = params.state or secrets.token_hex(16)
        # Generate PKCE challenge
        code_verifier: str = self._generate_code_verifier()
        code_challenge: str = self._generate_code_challenge(code_verifier)

        # Store the state mapping
        self.state_mapping[state] = {
            "redirect_uri": str(params.redirect_uri),
            "code_verifier": code_verifier,
            "code_challenge": params.code_challenge,
            "redirect_uri_provided_explicitly": str(
                params.redirect_uri_provided_explicitly
            ),
            "client_id": client.client_id,
        }

        auth_url: str = (
            f"{authorization_endpoint}"
            f"?client_id={self.configs.oauth.client_id}"
            f"&redirect_uri={self.configs.oauth.callback_url(self.configs.server_url)}"
            f"&scope={self.configs.oauth.scopes}"
            f"&state={state}"
            f"&code_challenge={code_challenge}"
            "&code_challenge_method=S256"
            "&response_type=code"
        )

        logger.debug(f"Redirecting the request to authorization URL: {auth_url}")
        return auth_url

    async def handle_mcp_oauth_callback(self, code: str, state: str) -> str:
        """Handle OAuth redirect."""
        state_data: dict[str, str] | None = self.state_mapping.get(state)
        if not state_data:
            raise HTTPException(400, "Invalid state parameter")

        redirect_uri: str = state_data["redirect_uri"]
        code_challenge: str = state_data["code_challenge"]
        redirect_uri_provided_explicitly: bool = (
            state_data["redirect_uri_provided_explicitly"] == "True"
        )
        client_id: str = state_data["client_id"]
        code_verifier: str = state_data["code_verifier"]

        token_endpoint: str = await self._get_token_endpoint()

        # Exchange code for token
        async with create_mcp_http_client() as client:
            response = await client.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.configs.oauth.client_id,
                    "client_secret": self.configs.oauth.client_secret,
                    "code": code,
                    "redirect_uri": self.configs.oauth.callback_url(
                        self.configs.server_url
                    ),
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
            )

            if response.status_code != 200:
                logger.debug(f"Failed to exchange code for token: {response}")
                raise HTTPException(400, "Failed to exchange code for token")
            
            data: dict = response.json()

            logger.debug(f"Received token response: {data}")

            if "error" in data:
                logger.debug(f"Unable to generate access token: {data}")
                raise HTTPException(400, data.get("error_description", data["error"]))

            access_token: str = data["access_token"]
            expires_in: int = data.get("expires_in", 3600)

            # Create MCP authorization code
            mcp_auth_code: str = f"fhir_mcp_{secrets.token_hex(16)}"
            self.auth_codes[mcp_auth_code] = AuthorizationCode(
                code=mcp_auth_code,
                client_id=client_id,
                redirect_uri=AnyHttpUrl(redirect_uri),
                redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
                expires_at=int(time.time()) + expires_in,
                scopes=self.configs.oauth.scopes_list,
                code_challenge=code_challenge,
            )

            self.tokens[access_token] = AccessToken(
                token=access_token,
                client_id=client_id,
                scopes=self.configs.oauth.scopes_list,
                expires_at=int(time.time()) + expires_in,
            )

        del self.state_mapping[state]
        return construct_redirect_uri(redirect_uri, code=mcp_auth_code, state=state)

    #
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        """Load an authorization code."""
        return self.auth_codes.get(authorization_code)

    #
    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """Exchange authorization code for tokens."""
        if authorization_code.code not in self.auth_codes:
            raise ValueError("Invalid authorization code")

        # Generate MCP access token
        mcp_token: str = f"fhir_mcp_{secrets.token_hex(32)}"

        # Store MCP token
        self.tokens[mcp_token] = AccessToken(
            token=mcp_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(authorization_code.expires_at),
        )

        # Find access token for this client
        access_token: str | None = next(
            (
                token
                for token, data in self.tokens.items()
                if data.client_id == client.client_id
            ),
            None,
        )

        # Store mapping between MCP access token and third-party access token
        if access_token:
            self.token_mapping[mcp_token] = access_token

        del self.auth_codes[authorization_code.code]

        return OAuthToken(
            access_token=mcp_token,
            token_type="bearer",
            expires_in=int(authorization_code.expires_at),
            scope=" ".join(authorization_code.scopes),
        )

    #
    async def load_access_token(self, token: str) -> AccessToken | None:
        """Load and validate an access token."""
        access_token = self.tokens.get(token)
        if not access_token:
            return None

        # Check if expired
        if access_token.expires_at and access_token.expires_at < time.time():
            del self.tokens[token]
            return None

        return access_token

    #
    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        """Load a refresh token - not supported."""
        return None

    #
    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Exchange refresh token"""
        raise NotImplementedError("Not supported")

    #
    async def revoke_token(
        self, token: str, token_type_hint: str | None = None
    ) -> None:
        """Revoke a token."""
        if token in self.tokens:
            del self.tokens[token]

    async def _discover_oauth_metadata(self) -> OAuthMetadata | None:

        return await discover_oauth_metadata(
            metadata_url=self.configs.oauth.metadata_url,
            headers={"Accept": "application/json"},
        )

    # Replace endpoint extraction methods
    async def _get_authorization_endpoint(self) -> str:
        return get_endpoint(self._metadata, "authorization_endpoint")

    async def _get_token_endpoint(self) -> str:
        return get_endpoint(self._metadata, "token_endpoint")

    def _generate_code_verifier(self) -> str:
        """Generate a cryptographically random code verifier for PKCE."""
        return generate_code_verifier(128)

    def _generate_code_challenge(self, code_verifier: str) -> str:
        """Generate a code challenge from a code verifier using SHA256."""
        return generate_code_challenge(code_verifier)
