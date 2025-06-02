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
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.exceptions import HTTPException

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

logger = logging.getLogger(__name__)


class OAuth2Config(BaseSettings):
    consumer_key: str
    consumer_secret: str
    redirection_url: str
    token_endpoint: str
    authorize_endpoint: str
    scopes: str


class ServerSettings(BaseSettings):
    """Contains settings for the MCP server."""

    model_config = SettingsConfigDict(
        env_prefix="FHIR_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # consumer_key: str = "2Us5BrHi13pG6_wafyRGBshrj2Aa"
    # consumer_secret: str = "aSAOfIM6MWWFM8fF2dP7kWUYk2HZ8mrnRA5JDKEi7fYa"
    # redirection_url: str = "http://localhost:8000/mcp/healthcare/redirect"
    # token_endpoint: str = "https://api.asgardeo.io/t/wso2healthcare/oauth2/token"
    # revoke_endpoint: str = "https://api.asgardeo.io/t/wso2healthcare/oauth2/revoke"
    # authorize_endpoint: str = "https://api.asgardeo.io/t/wso2healthcare/oauth2/authorize"

    # Server settings
    host: str = "localhost"
    port: int = 8000
    server_url: AnyHttpUrl = AnyHttpUrl(f"http://{host}:{port}")
    base_url: str = "https://hapi.fhir.org/baseR4"

    # OAuth2 settings
    oauth2: OAuth2Config

    @property
    def scopes(self) -> list[str]:
        # If the raw value is a string, split on commas
        if isinstance(self.oauth2.scopes, str):
            return [
                scopes.strip()
                for scopes in self.oauth2.scopes.split(" ")
                if scopes.strip()
            ]
        return [self.oauth2.scopes]

    def __init__(self, **data):
        """Initialize settings with values from environment variables"""
        super().__init__(**data)


class OAuth2ServerProvider(OAuthAuthorizationServerProvider):

    def __init__(self, settings: ServerSettings):
        self.settings = settings
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self.tokens: dict[str, AccessToken] = {}
        self.state_mapping: dict[str, dict[str, str]] = {}
        self.token_mapping: dict[str, str] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Get OAuth client information."""
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull):
        """Register a new OAuth client."""
        self.clients[client_info.client_id] = client_info

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Generate an authorization URL for OAuth flow."""
        state: str = params.state or secrets.token_hex(16)

        # Store the state mapping
        self.state_mapping[state] = {
            "redirect_uri": str(params.redirect_uri),
            "code_challenge": params.code_challenge,
            "redirect_uri_provided_explicitly": str(
                params.redirect_uri_provided_explicitly
            ),
            "client_id": client.client_id,
        }

        auth_url: str = (
            f"{self.settings.oauth2.authorize_endpoint}"
            f"?client_id={self.settings.oauth2.consumer_key}"
            f"&redirect_uri={self.settings.oauth2.redirection_url}"
            f"&scope={self.settings.oauth2.scopes}"
            f"&state={state}"
            "&response_type=code"
        )

        return auth_url

    async def handle_redirect(self, code: str, state: str) -> str:
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

        # Exchange code for token
        async with create_mcp_http_client() as client:
            response = await client.post(
                self.settings.oauth2.token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.settings.oauth2.consumer_key,
                    "client_secret": self.settings.oauth2.consumer_secret,
                    "code": code,
                    "redirect_uri": self.settings.oauth2.redirection_url,
                },
                headers={"Accept": "application/json"},
            )

            if response.status_code != 200:
                raise HTTPException(400, "Failed to exchange code for token")

            data: dict = response.json()

            if "error" in data:
                logger.debug(f"Unable to generate access token: {data}")
                raise HTTPException(400, data.get("error_description", data["error"]))

            access_token: str = data["access_token"]
            expires_in: int = data.get("expires_in", 3600)

            # Create MCP authorization code
            mcp_auth_code: str = f"mcp_{secrets.token_hex(16)}"
            self.auth_codes[mcp_auth_code] = AuthorizationCode(
                code=mcp_auth_code,
                client_id=client_id,
                redirect_uri=AnyHttpUrl(redirect_uri),
                redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
                expires_at=int(time.time()) + expires_in,
                scopes=self.settings.scopes,
                code_challenge=code_challenge,
            )

            self.tokens[access_token] = AccessToken(
                token=access_token,
                client_id=client_id,
                scopes=self.settings.scopes,
                expires_at=int(time.time()) + expires_in,
            )

        del self.state_mapping[state]
        return construct_redirect_uri(redirect_uri, code=mcp_auth_code, state=state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        """Load an authorization code."""
        return self.auth_codes.get(authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """Exchange authorization code for tokens."""
        if authorization_code.code not in self.auth_codes:
            raise ValueError("Invalid authorization code")

        # Generate MCP access token
        mcp_token: str = f"mcp_{secrets.token_hex(32)}"

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

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        """Load a refresh token - not supported."""
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Exchange refresh token"""
        raise NotImplementedError("Not supported")

    async def revoke_token(
        self, token: str, token_type_hint: str | None = None
    ) -> None:
        """Revoke a token."""
        if token in self.tokens:
            del self.tokens[token]
