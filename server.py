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

from mcp.server.fastmcp import FastMCP

import logging
from constants import FHIR_BASE_URL
from utils import get_capability_statement, get_fhir_resource, trim_resource
from typing import Dict, Any, Optional


mcp: FastMCP = FastMCP(name="healthcare-mcp-server", json_response=True)

logger: logging.Logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s {%(name)s.%(funcName)s:%(lineno)d} - %(message)s",
)


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
        data: Dict[str, Any] = get_capability_statement(FHIR_BASE_URL)
        for resource in data["rest"][0]["resource"]:
            if resource.get("type") == type:
                logger.info(f"Resource type '{type}' found in capabilitystatement.")
                return {
                    "type": resource.get("type"),
                    "searchParam": trim_resource(resource.get("searchParam", [])),
                    "operation": trim_resource(resource.get("operation", [])),
                }
        logger.info(f"Resource type '{type}' not found in capabilitystatement.")
    except Exception as e:
        logger.exception(
            f"Error while parsing capabilitystatement for resource_type '{type}': {e}"
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

        fhir_resource_url: str = f"{FHIR_BASE_URL}/{type}"
        if operation:
            operation = operation if operation.startswith('$') else f'${operation}'
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


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
