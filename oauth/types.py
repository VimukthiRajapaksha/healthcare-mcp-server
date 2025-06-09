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

from typing import Dict
from pydantic import AnyHttpUrl, BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from mcp.shared.auth import OAuthClientInformationFull


class BaseOAuthConfigs(BaseSettings):
    client_id: str
    client_secret: str
    scopes: str

    @property
    def scopes_list(self) -> list[str]:
        # If the raw value is a string, split on commas
        if isinstance(self.scopes, str):
            return [
                scopes.strip() for scopes in self.scopes.split(" ") if scopes.strip()
            ]
        return [self.scopes]


class MCPOAuthConfigs(BaseOAuthConfigs):
    metadata_url: str

    def callback_url(
        self, server_url: str, suffix: str = "/oauth/callback"
    ) -> AnyHttpUrl:
        return AnyHttpUrl(f"{server_url.rstrip('/')}{suffix}")


class FHIROAuthConfigs(BaseOAuthConfigs):
    base_url: str

    def callback_url(
        self, server_url: str, suffix: str = "/fhir/callback"
    ) -> AnyHttpUrl:
        return AnyHttpUrl(f"{server_url.rstrip('/')}{suffix}")

    @property
    def discovery_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/.well-known/smart-configuration"

    @property
    def metadata_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/metadata?_format=json"


class ServerConfigs(BaseSettings):
    """Contains environment configurations of the MCP server."""

    model_config = SettingsConfigDict(
        env_prefix="HEALTHCARE_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Server settings
    host: str = "localhost"
    port: int = 8000
    server_url: str = f"http://{host}:{port}"

    # OAuth2 settings
    oauth: MCPOAuthConfigs

    fhir: FHIROAuthConfigs

    def __init__(self, **data):
        """Initialize settings with values from environment variables"""
        super().__init__(**data)


class OAuthMetadata(BaseModel):
    """
    OAuth 2.0 Authorization Server Metadata.
    """

    issuer: AnyHttpUrl
    authorization_endpoint: AnyHttpUrl
    token_endpoint: AnyHttpUrl
    registration_endpoint: AnyHttpUrl | None = None
    scopes_supported: list[str] | None = None
    response_types_supported: list[str]
    response_modes_supported: list[str] | None = None
    grant_types_supported: list[str] | None = None
    token_endpoint_auth_methods_supported: list[str] | None = None
    token_endpoint_auth_signing_alg_values_supported: list[str] | None = None
    service_documentation: AnyHttpUrl | None = None
    ui_locales_supported: list[str] | None = None
    op_policy_uri: AnyHttpUrl | None = None
    op_tos_uri: AnyHttpUrl | None = None
    revocation_endpoint: AnyHttpUrl | None = None
    revocation_endpoint_auth_methods_supported: list[str] | None = None
    revocation_endpoint_auth_signing_alg_values_supported: None = None
    introspection_endpoint: AnyHttpUrl | None = None
    introspection_endpoint_auth_methods_supported: list[str] | None = None
    introspection_endpoint_auth_signing_alg_values_supported: None = None
    code_challenge_methods_supported: list[str] | None = None


class OAuthToken(BaseModel):
    """
    OAuth 2.0 token with metadata.
    """

    access_token: str
    token_type: str
    expires_in: int | None = None
    scope: str | None = None
    refresh_token: str | None = None
    expires_at: float | None = None


class TokenStorage:
    """In memory token storage."""

    _tokens: Dict[str, OAuthToken] | None
    _client_info: OAuthClientInformationFull | None

    def __init__(
        self,
        tokens: Dict[str, OAuthToken] | None = None,
        client_info: OAuthClientInformationFull | None = None,
    ):
        self._tokens: Dict[str, OAuthToken] | None = tokens
        self._client_info: OAuthClientInformationFull | None = client_info

    def get_tokens(self) -> Dict[str, OAuthToken] | None:
        return self._tokens

    def get_token(self, token_id: str) -> OAuthToken | None:
        if self._tokens:
            return self._tokens.get(token_id)
        return None

    def set_tokens(self, tokens: Dict[str, OAuthToken]) -> None:
        self._tokens = tokens

    def set_token(self, token_id: str, token: OAuthToken) -> None:
        if self._tokens is None:
            self._tokens = {}
        self._tokens[token_id] = token

    def get_client_info(self) -> OAuthClientInformationFull | None:
        return self._client_info

    def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client_info = client_info
