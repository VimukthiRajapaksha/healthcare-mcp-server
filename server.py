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

from oauth.client_provider import FHIRClientProvider
from oauth.common import handle_failed_authentication, handle_successful_authentication
from oauth.server_provider import OAuthServerProvider
from oauth.types import OAuthToken, ServerConfigs, TokenStorage
from utils import get_capability_statement, get_fhir_resource, trim_resource
from typing import Dict, Any, Literal, Optional

from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response, HTMLResponse

from mcp.server.auth.middleware.auth_context import get_access_token

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp.server import FastMCP
from mcp.shared.auth import OAuthClientInformationFull
import webbrowser
import sys
import asyncio

logger: logging.Logger = logging.getLogger(__name__)


server_configs: ServerConfigs = ServerConfigs()

server_provider: OAuthServerProvider = OAuthServerProvider(configs=server_configs)

auth_settings: AuthSettings = AuthSettings(
    issuer_url=AnyHttpUrl(server_configs.server_url),
    client_registration_options=ClientRegistrationOptions(
        enabled=True,
        valid_scopes=server_configs.oauth.scopes_list,
        default_scopes=server_configs.oauth.scopes_list,
    ),
    required_scopes=server_configs.oauth.scopes_list,
)

mcp: FastMCP = FastMCP(
    name="FHIR MCP Server",
    instructions="FHIR MCP Server",
    auth_server_provider=server_provider,
    host=server_configs.host,
    port=server_configs.port,
    debug=True,
    auth=auth_settings,
    json_response=True,
    stateless_http=True,
)


async def webbrowser_redirect_handler(authorization_url: str):
    print(f"Opening user's browser with URL: {authorization_url}")
    webbrowser.open_new_tab(authorization_url)


client_info: OAuthClientInformationFull = OAuthClientInformationFull(
    client_name="FHIR MCP Client",
    redirect_uris=[server_configs.fhir.callback_url(server_configs.server_url)],
    scope=server_configs.fhir.scopes,
    client_id=server_configs.fhir.client_id,
    client_secret=server_configs.fhir.client_secret,
)

token_storage: TokenStorage = TokenStorage(client_info=client_info)

client_provider: FHIRClientProvider = FHIRClientProvider(
    discovery_url=server_configs.fhir.discovery_url,
    client_metadata=client_info,
    storage=token_storage,
    redirect_handler=webbrowser_redirect_handler,
)


@mcp.custom_route("/fhir/callback", methods=["GET"])
async def oauth_callback(request: Request) -> HTMLResponse:
    """Handle FHIR OAuth redirect."""
    code: str | None = request.query_params.get("code")
    state: str | None = request.query_params.get("state")

    if not code or not state:
        return handle_failed_authentication("Missing code or state parameter")

    try:
        await client_provider.handle_fhir_oauth_callback(code, state)
        return handle_successful_authentication()
    except Exception as ex:
        logger.error(
            "Error occurred while handling FHIR oauth callback. Caused by, ",
            exc_info=ex,
        )
        return handle_failed_authentication("Something went wrong.")


@mcp.custom_route("/oauth/callback", methods=["GET"])
async def redirect_handler(request: Request) -> Response:
    """Handle MCP OAuth redirect."""
    code: str | None = request.query_params.get("code")
    state: str | None = request.query_params.get("state")

    if not code or not state:
        return handle_failed_authentication("Missing code or state parameter")

    try:
        redirect_uri: str = await server_provider.handle_mcp_oauth_callback(code, state)
        return RedirectResponse(status_code=302, url=redirect_uri)
    except Exception as ex:
        logger.error(
            "Error occurred while handling MCP oauth callback. Caused by, ", exc_info=ex
        )
        return handle_failed_authentication("Something went wrong.")


def get_mcp_client_token() -> str:
    """Get the access token for the authenticated client."""
    access_token = get_access_token()
    if not access_token:
        raise ValueError("Not authenticated")

    # Get access token from mapping
    access_token = server_provider.token_mapping.get(access_token.token)

    if not access_token:
        raise ValueError("No access token found for MCP client")

    return access_token


@mcp.tool()
async def get_available_resource_types(type: str) -> Dict[str, Any]:
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
        data: Dict[str, Any] = await get_capability_statement(
            server_configs.fhir.metadata_url
        )
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
async def search_fhir(
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

    client_access_token: str = get_mcp_client_token()
    user_access_token: OAuthToken | None = await client_provider.get_access_token(
        client_access_token
    )

    try:
        if not type:
            logger.error("search_fhir failed: 'type' is a mandatory field.")
            return {"error": "type is a mandatory field"}

        if not user_access_token:
            # Wait for user_access_token to become available, with a timeout
            for _ in range(30):  # Try for up to 30 seconds
                user_access_token: OAuthToken | None = (
                    client_provider.storage.get_token(client_access_token)
                )
                if user_access_token:
                    break
                await asyncio.sleep(1)
            if not user_access_token:
                logger.error("Failed to obtain user access token.")
                return {"error": "Failed to obtain user access token"}

        fhir_resource_url: str = f"{server_configs.fhir.base_url.rstrip('/')}/{type}"
        if operation:
            operation = operation if operation.startswith("$") else f"${operation}"
            fhir_resource_url: str = f"{fhir_resource_url}/{operation}"
        params: Optional[Dict[str, str]] = searchParam if searchParam else None

        data: Dict[str, Any] = await get_fhir_resource(
            fhir_resource_url,
            params=params,
            headers={"Authorization": f"Bearer {user_access_token.access_token}"},
        )

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


@click.command()
@click.option(
    "--transport", default="streamable-http", help="Transport protocol to use"
)
@click.option("--log-level", default="INFO", help="Log level to use")
def main(
    transport: Literal["stdio", "sse", "streamable-http"],
    log_level: Literal["DEBUG", "INFO", "ERROR"],
) -> int:
    try:
        logger.setLevel(log_level.upper())
        logger.info(f"Starting FHIR MCP server with {transport} transport")
        mcp.run(transport=transport)
    except ValueError as e:
        logger.error(f"Unable to run the FHIR MCP server. Caused by, ", exc_info=e)
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s {%(name)s.%(funcName)s:%(lineno)d} - %(message)s",
    )
    sys.exit(main())
