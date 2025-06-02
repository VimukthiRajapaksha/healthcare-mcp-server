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

import click
from mcp.server.fastmcp import FastMCP

import logging
from oauth import OAuth2ServerProvider, ServerSettings
from utils import get_capability_statement, get_fhir_resource, trim_resource
from typing import Dict, Any, Literal, Optional

from pydantic import AnyHttpUrl
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from mcp.server.auth.middleware.auth_context import get_access_token

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp.server import FastMCP

logger: logging.Logger = logging.getLogger(__name__)


def create_fhir_mcp_server(settings: ServerSettings) -> FastMCP:
    oauth_provider: OAuth2ServerProvider = OAuth2ServerProvider(settings)
    auth_settings: AuthSettings = AuthSettings(
        issuer_url=AnyHttpUrl(settings.server_url),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=settings.scopes,
            default_scopes=settings.scopes,
        ),
        required_scopes=settings.scopes,
    )

    mcp: FastMCP = FastMCP(
        name="FHIR MCP Server",
        instructions="FHIR MCP Server",
        auth_server_provider=oauth_provider,
        host=settings.host,
        port=settings.port,
        debug=True,
        auth=auth_settings,
        json_response=True,
        stateless_http=True
    )

    @mcp.custom_route("/fhir/mcp/redirect", methods=["GET"])
    async def redirect_handler(request: Request) -> Response:
        """Handle OAuth redirect."""
        code: str | None = request.query_params.get("code")
        state: str | None = request.query_params.get("state")

        if not code or not state:
            raise HTTPException(400, "Missing code or state parameter")

        try:
            redirect_uri: str = await oauth_provider.handle_redirect(code, state)
            return RedirectResponse(status_code=302, url=redirect_uri)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                "Error occurred while handling oauth callbank. Caused by, ", exc_info=e
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "server_error",
                    "error_description": "Unexpected Error",
                },
            )

    def get_token() -> str:
        """Get the GitHub token for the authenticated user."""
        access_token = get_access_token()
        if not access_token:
            raise ValueError("Not authenticated")

        # Get GitHub token from mapping
        github_token = oauth_provider.token_mapping.get(access_token.token)

        if not github_token:
            raise ValueError("No GitHub token found for user")

        return github_token

    @mcp.tool()
    def get_available_resource_types(type: str) -> Dict[str, Any]:
        """
        Retrieves the valid search parameters and available operations for a specified FHIR resource type.

        Use this tool before attempting any `search_fhir` calls whenever you need to discover or validate which `searchParam` keys
        and `operation` values are allowed. It will not perform any searches itself or return resource instances, only metadata
        about what search inputs are available.

        Args:
            type (str): The type of core FHIR resource (e.g., "Patient", "Observation", "Encounter").

        Returns:
            Dict[str, Any]:
                A dictionary containing:
                - "type": the requested resource type (if available).
                - "searchParam": a Dict[str, str] of searchable parameter names to their descriptions for that resource type.
                - "operation": a Dict[str, str] of supported custom operation names to their descriptions.
        """

        logger.info(f"Tool get_available_resources called with resource_type='{type}'")
        try:
            data: Dict[str, Any] = get_capability_statement(settings.base_url)
            for resource in data["rest"][0]["resource"]:
                if resource.get("type") == type:
                    logger.info(f"Resource type '{type}' found in the CapabilityStatement.")
                    return {
                        "type": resource.get("type"),
                        "searchParam": trim_resource(resource.get("searchParam", [])),
                        "operation": trim_resource(resource.get("operation", [])),
                    }
            logger.info(f"Resource type '{type}' not found in the CapabilityStatement.")
        except Exception as e:
            logger.exception(
                f"Error while parsing the CapabilityStatement for resource_type '{type}': {e}"
            )
        return {}

    @mcp.tool()
    def search_fhir(
        type: str,
        searchParam: Optional[Dict[str, str]] = None,
        operation: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a FHIR search or custom operation on a given resource type.

        Use this function only after retrieving valid `searchParam` and/or `operation`
        values from `get_available_resource_types`. It returns the raw FHIR bundle
        or the result of the specified operation. Do not call search_fhir directly without
        first retrieving and selecting valid parameters via get_available_resource_types.

        Args:
            type (str): The FHIR resource type to query (e.g., "Patient").
            searchParam (Optional[Dict[str, str]]): A mapping of one or more search parameter names to values,
                as returned by `get_available_resource_types`.
            operation (Optional[str]): The name of a custom FHIR operation (e.g., "$validate"),
                as returned by `get_available_resource_types`.

        Returns:
            Dict[str, Any]: A dictionary containing the FHIR search result bundle or operation output.
        """

        logger.info(
            f"Tool search_fhir called with type='{type}', searchParam={searchParam}, operation={operation}"
        )
        try:
            if not type:
                logger.error("search_fhir failed: 'type' is a mandatory field.")
                return {"error": "type is a mandatory field"}

            fhir_resource_url: str = f"{settings.base_url}/{type}"
            if operation:
                operation = operation if operation.startswith("$") else f"${operation}"
                fhir_resource_url: str = f"{fhir_resource_url}/{operation}"
            params: Optional[Dict[str, str]] = searchParam if searchParam else None

            data: Dict[str, Any] = get_fhir_resource(fhir_resource_url, params=params)

            if "entry" in data and isinstance(data["entry"], list):
                logger.info(
                    f"search_fhir found {len(data['entry'])} entries for type '{type}'"
                )
                return {
                    "entry": [
                        entry.get("resource")
                        for entry in data["entry"]
                        if "resource" in entry
                    ]
                }

            logger.info(
                f"search_fhir: No 'entry' array found in response for type '{type}'"
            )
            return data
        except Exception as e:
            logger.exception(
                f"Error while parsing fhir search request for resource_type '{type}': {e}"
            )
        return {}

    return mcp


@click.command()
@click.option("--port", default=8000, help="Port to listen on")
@click.option("--host", default="localhost", help="Host to bind to")
@click.option(
    "--transport", default="streamable-http", help="Transport protocol to use"
)
def main(port: int, host: str, transport: Literal["streamable-http"]) -> int:
    try:
        mcp: FastMCP = create_fhir_mcp_server(ServerSettings(host=host, port=port))
        logger.info(f"Starting FHIR MCP server with {transport} transport")
        mcp.run(transport=transport)
    except ValueError as e:
        logger.error(f"Unable to run the FHIR MCP server. Caused by, ", exc_info=e)
        return 1
    return 0
