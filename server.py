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
from fhirpy import AsyncFHIRClient
from fhirpy.lib import AsyncFHIRResource
from fhirpy.base.exceptions import OperationOutcome
from fhirpy.base.searchset import Raw
from mcp.server.fastmcp import FastMCP

import logging

from fhir_utils import (
    create_async_fhir_client,
    get_operation_outcome_exception,
    get_operation_outcome_required_error,
)
from oauth.client_provider import FHIRClientProvider
from oauth.common import handle_failed_authentication, handle_successful_authentication
from oauth.server_provider import OAuthServerProvider
from oauth.types import OAuthToken, ServerConfigs, TokenStorage
from utils import get_capability_statement, trim_resource
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
async def handle_fhir_server_callback(request: Request) -> HTMLResponse:
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
async def handle_auth_server_callback(request: Request) -> Response:
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


async def get_client_access_token() -> str:
    """Get the access token for the authenticated client."""
    access_token = get_access_token()
    if not access_token:
        raise ValueError("Not authenticated")

    # Get access token from mapping
    access_token = server_provider.token_mapping.get(access_token.token)

    if not access_token:
        raise ValueError("No access token found for MCP client")

    return access_token


async def get_user_access_token() -> OAuthToken | None:
    """Get the access token for the authenticated user."""
    client_access_token: str = await get_client_access_token()
    user_access_token: OAuthToken | None = await client_provider.get_access_token(
        client_access_token
    )

    if not user_access_token:
        # Wait for user_access_token to become available, with a timeout
        for _ in range(30):  # Try for up to 30 seconds
            user_access_token: OAuthToken | None = client_provider.storage.get_token(
                client_access_token
            )
            if user_access_token:
                break
            await asyncio.sleep(1)
        if not user_access_token:
            logger.error("Failed to obtain user access token.")
    return user_access_token


async def get_bundle_entries(bundle: Dict[str, Any]) -> Dict[str, Any]:
    if "entry" in bundle and isinstance(bundle["entry"], list):
        logger.debug(f"found {len(bundle['entry'])} entries for type '{type}'")
        return {
            "entry": [
                entry.get("resource")
                for entry in bundle["entry"]
                if "resource" in entry
            ]
        }
    return bundle


async def get_async_fhir_client() -> AsyncFHIRClient:

    user_token: OAuthToken | None = await get_user_access_token()
    if not user_token:
        raise ValueError("User is not authenticated")

    return await create_async_fhir_client(
        config=server_configs.fhir, access_token=user_token.access_token
    )


@mcp.tool()
async def get_capabilities(type: str) -> Dict[str, Any]:
    """
    Retrieves metadata about a specified FHIR resource type, including its supported search parameters and custom operations.

    This tool should be used at the start of any workflow where you need to discover what queries or operations are permitted
    against that resource (e.g., before calling search, read, or create). Do not use this tool to fetch actual resources.
    It only returns definitions and descriptions of capabilities, not resource instances. Because FHIR defines different search
    parameters and operations per resource type, this tool ensures your subsequent calls use valid inputs.

    Args:
        type (str): The FHIR resource type name (e.g., "Patient", "Observation", "Encounter").
                Must exactly match one of the core or profile-defined resource types supported by the server.

    Returns:
        Dict[str, Any]:
            A dictionary containing:
            - "type" (str): The requested resource type (if available) or empty.
            - "searchParam" (Dict[str, str]): A map of FHIR search-parameter names. Each key is the parameter name
                    (e.g., "family", "_id", "_lastUpdated"), and each value is the FHIR-provided description of that parameter's meaning and usage constraints.
            - "operation" (Dict[str, str]): A map of custom FHIR operation names to their descriptions.
                    Each key is the operation name (e.g., "$validate"), and each value explains the operation's purpose.
    """

    logger.debug(f"Invoked with resource_type='{type}'")
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
    except Exception as ex:
        logger.exception(
            f"Error while executing the FHIR metadata interaction for resource_type '{type}'. Caused by, ",
            exc_info=ex,
        )
    return await get_operation_outcome_exception()


@mcp.tool()
async def search(
    type: str, searchParam: Dict[str, str]
) -> list[AsyncFHIRResource] | Dict[str, Any]:
    """
    Executes a standard FHIR search interaction on a given resource type, returning a bundle or list of matching resources.

    Use this when you need to query for multiple resources based on one or more search-parameters.
    Do not use this tool for create, update, or delete operations, and be aware that large result sets may be paginated by the FHIR server.

    Args:
        type (str): The FHIR resource type name (e.g., "MedicationRequest", "Condition", "Procedure").
                Must exactly match one of the core or profile-defined resource types supported by the server.
        searchParam (Dict[str, str]): A mapping of FHIR search parameter names to their desired values (e.g., {"family":"Smith","birthdate":"1970-01-01"}).
                These parameters refine queries for operation-specific query qualifiers.
                Only parameters exposed by `get_capabilities` for that resource type are valid.

    Returns:
        Dict[str, Any]: A dictionary containing the full FHIR resource instance matching the search criteria.
    """

    logger.debug(f"Invoked with type='{type}' and searchParam={searchParam}")

    try:
        if not type:
            logger.error("Unable to perform search: 'type' is a mandatory field.")
            return await get_operation_outcome_required_error("type")

        client: AsyncFHIRClient = await get_async_fhir_client()
        return await client.resources(type).search(Raw(**searchParam)).fetch()
    except Exception as ex:
        logger.exception(
            f"Error while executing the FHIR search interaction for resource_type '{type}'. Caused by, ",
            exc_info=ex,
        )
    return await get_operation_outcome_exception()


@mcp.tool()
async def read(
    type: str,
    id: str,
    searchParam: Optional[Dict[str, str]] = None,
    operation: Optional[str] = "",
) -> Dict[str, Any]:
    """
    Performs a FHIR "read" interaction to retrieve a single resource instance by its type and resource ID,
    optionally refining the response with search parameters or custom operations.

    Use it when you know the exact resource ID and require that one resource; do not use it for bulk queries.
    If additional query-level parameters or operations are needed (e.g., _elements or $validate), include them in searchParam or operation.

    Args:
        type (str): The FHIR resource type name (e.g., "DiagnosticReport", "AllergyIntolerance", "Immunization").
                Must exactly match one of the core or profile-defined resource types supported by the server.
        id (str): The logical ID of a specific FHIR resource instance.
        searchParam (Dict[str, str]): A mapping of FHIR search parameter names to their desired values (e.g., {"device-name":"glucometer"}).
                These parameters refine queries for operation-specific query qualifiers.
                Only parameters exposed by `get_capabilities` for that resource type are valid.
        operation (Optional[str]): The name of a custom FHIR operation or extended query defined for the resource (e.g., "$everything").
                Must match one of the operation names returned by `get_capabilities`.

    Returns:
        Dict[str, Any]: A dictionary containing the single FHIR resource instance of the requested type and id.
    """

    logger.debug(
        f"Invoked with type='{type}', id={id}, searchParam={searchParam}, and operation={operation}"
    )

    try:
        if not type:
            logger.error("Unable to perform read: 'type' is a mandatory field.")
            return await get_operation_outcome_required_error("type")

        client: AsyncFHIRClient = await get_async_fhir_client()
        bundle: dict = await client.resource(resource_type=type, id=id).execute(
            operation=operation or "", method="GET", params=searchParam
        )

        return await get_bundle_entries(bundle=bundle)
    except Exception as ex:
        logger.exception(
            f"Error while executing the FHIR read interaction for resource_type '{type}'. Caused by, ",
            exc_info=ex,
        )
    return await get_operation_outcome_exception()


@mcp.tool()
async def create(
    type: str,
    payload: Dict[str, Any],
    searchParam: Optional[Dict[str, str]] = None,
    operation: Optional[str] = "",
) -> Dict[str, Any]:
    """
    Executes a FHIR "create" interaction to persist a new resource of the specified type. It is required to supply the full resource payload in JSON form.

    Use this tool when you need to add new data (e.g., a new Patient or Observation). Do not call it to update existing resources; for updates, use patch.
    Note that servers may reject resources that violate profiles or mandatory bindings.

    Args:
        type (str): The FHIR resource type name (e.g., "Device", "CarePlan", "Goal").
                Must exactly match one of the core or profile-defined resource types supported by the server.
        payload (Dict[str, str]): A JSON object representing the full FHIR resource body to be created.
                It must include all required elements of the resource's profile.
        searchParam (Dict[str, str]): A mapping of FHIR search parameter names to their desired values (e.g., {"address-city":"Boston"}).
                These parameters refine queries for operation-specific query qualifiers.
                Only parameters exposed by `get_capabilities` for that resource type are valid.
        operation (Optional[str]): The name of a custom FHIR operation or extended query defined for the resource (e.g., "$evaluate").
                Must match one of the operation names returned by `get_capabilities`.

    Returns:
        Dict[str, Any]: A dictionary containing the newly created FHIR resource, including server-assigned fields (id, meta.versionId, meta.lastUpdated,
                and any server-added extensions). Reflects exactly what was persisted.
    """

    logger.debug(
        f"Invoked with type='{type}', payload={payload}, searchParam={searchParam}, and operation={operation}"
    )

    try:
        if not type:
            logger.error("Unable to perform create: 'type' is a mandatory field.")
            return await get_operation_outcome_required_error("type")

        client: AsyncFHIRClient = await get_async_fhir_client()
        bundle: dict = await client.resource(resource_type=type).execute(
            operation=operation or "", data=payload, params=searchParam
        )

        return await get_bundle_entries(bundle=bundle)
    except OperationOutcome as ex:
        logger.exception(
            f"Error while creating the FHIR resource:'{type}', Caused by,", exc_info=ex
        )
        return ex.resource["issue"] or await get_operation_outcome_exception()
    except Exception as ex:
        logger.exception(
            f"Error while executing the FHIR create interaction for resource_type '{type}'. Caused by, ",
            exc_info=ex,
        )
    return await get_operation_outcome_exception()


@mcp.tool()
async def patch(
    type: str,
    id: str,
    payload: Dict[str, Any],
    searchParam: Optional[Dict[str, str]] = None,
    operation: Optional[str] = "",
) -> Dict[str, Any]:
    """
    Applies a FHIR "patch" interaction to modify an existing resource by ID, using an RFC 6902 JSON-patch payload.

    Use it when you need to update parts of a resource without resending the entire body. Do not use this for creating resources,
    and ensure your payload conforms to the server's patch profile and that you have the latest version to avoid version conflicts.

    Args:
        type (str): The FHIR resource type name (e.g., "Location", "Organization", "Coverage").
        id (str): The logical ID of a specific FHIR resource instance.
                Must exactly match one of the core or profile-defined resource types supported by the server.
        payload (Dict[str, str]): A JSON object following the RFC 6902 patch syntax (an array of operations) of the FHIR resource to be patched
                (e.g., [{"op": "replace", "path": "/name/family", "value": "Doe"}]).
        searchParam (Dict[str, str]): A mapping of FHIR search parameter names to their desired values (e.g., {"patient":"Patient/54321","relationship":"father"}).
                These parameters refine queries for operation-specific query qualifiers.
                Only parameters exposed by `get_capabilities` for that resource type are valid.
        operation (Optional[str]): The name of a custom FHIR operation or extended query defined for the resource (e.g., "$lastn").
                Must match one of the operation names returned by `get_capabilities`.

    Returns:
        Dict[str, Any]: A dictionary containing the updated FHIR resource after applying the JSON Patch operations..
    """

    logger.debug(
        f"Invoked with type='{type}', id={id}, payload={payload}, searchParam={searchParam}, and operation={operation}"
    )

    try:
        if not type:
            logger.error("Unable to perform create: 'type' is a mandatory field.")
            return await get_operation_outcome_required_error("type")

        client: AsyncFHIRClient = await get_async_fhir_client()
        client.extra_headers = {"Content-Type": "application/json-patch+json"}
        bundle: dict = await client.resource(resource_type=type, id=id).execute(
            operation=operation or "", method="PATCH", data=payload, params=searchParam
        )
        return await get_bundle_entries(bundle=bundle)
    except OperationOutcome as ex:
        logger.exception(
            f"Error while patching the FHIR resource:'{type}', Caused by,", exc_info=ex
        )
        return ex.resource["issue"] or await get_operation_outcome_exception()
    except Exception as ex:
        logger.exception(
            f"Error while executing the FHIR patch interaction for resource_type '{type}'. Caused by, ",
            exc_info=ex,
        )
    return await get_operation_outcome_exception()


@mcp.tool()
async def delete(
    type: str,
    id: Optional[str] = "",
    searchParam: Optional[Dict[str, str]] = None,
    operation: Optional[str] = "",
) -> Dict[str, Any]:
    """
    Execute a FHIR "delete" interaction on a specific resource instance.

    Use this tool when you need to remove a single resource identified by its logical ID or optionally filtered by search parameters.
    The optional `id` parameter must match an existing resource instance when present. If you include `searchParam`,
    the server will perform a conditional delete, deleting the resource only if it matches the given criteria. If you supply `operation`,
    it will execute the named FHIR operation (e.g., `$expunge`) on the resource. Do not use this tool for bulk deletes across multiple
    This tool returns a FHIR `OperationOutcome` describing success or failure of the deletion.

    Args:
        type (str): The FHIR resource type name (e.g., "ServiceRequest", "Appointment", "HealthcareService").
        id (str): The logical ID of a specific FHIR resource instance.
                Must exactly match one of the core or profile-defined resource types supported by the server.
        payload (Dict[str, str]): A JSON object following the RFC 6902 patch syntax (an array of operations) of the FHIR resource to be patched
                (e.g., [{"op": "replace", "path": "/name/family", "value": "Doe"}]).
        searchParam (Dict[str, str]): A mapping of FHIR search parameter names to their desired values (e.g., {"category":"laboratory","issued:"2025-05-01"}).
                These parameters refine queries for operation-specific query qualifiers.
                Only parameters exposed by `get_capabilities` for that resource type are valid.
        operation (Optional[str]): The name of a custom FHIR operation or extended query defined for the resource (e.g., "$expand").
                Must match one of the operation names returned by `get_capabilities`.

    Returns:
        Dict[str, Any]: A dictionary containing the confirmation of deletion or details on why deletion failed.
    """

    logger.debug(
        f"Invoked with type='{type}', id={id}, searchParam={searchParam}, and operation={operation}"
    )

    try:
        if not type:
            logger.error("Unable to perform create: 'type' is a mandatory field.")
            return await get_operation_outcome_required_error("type")

        client: AsyncFHIRClient = await get_async_fhir_client()
        bundle: dict = await client.resource(resource_type=type, id=id).execute(
            operation=operation or "", method="DELETE", params=searchParam
        )
        return await get_bundle_entries(bundle=bundle)
    except OperationOutcome as ex:
        logger.exception(
            f"Error while deleting the FHIR resource:'{type}', Caused by,", exc_info=ex
        )
        return ex.resource["issue"] or await get_operation_outcome_exception()
    except Exception as ex:
        logger.exception(
            f"Error while executing the FHIR delete interaction for resource_type '{type}'. Caused by, ",
            exc_info=ex,
        )
    return await get_operation_outcome_exception()


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
