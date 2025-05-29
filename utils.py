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

import requests
from typing import List, Dict, Any, Optional
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s {%(name)s.%(funcName)s:%(lineno)d} - %(message)s",
)


def http_get(
    url: str, params: Optional[dict] = None, headers: Optional[dict] = None
) -> requests.Response:
    logger.info(f"http_get called with url='{url}', params={params}, headers={headers}")

    response = requests.get(url, params=params, headers=headers)
    logger.info(f"http_get received response with status code: {response.status_code}")
    return response


def get_fhir_resource(
    fhir_url: str, params: Optional[dict] = None, headers: Optional[dict] = None
) -> Dict[str, Any]:
    logger.info(
        f"get_fhir_resource called with fhir_url='{fhir_url}' and params={params}"
    )

    response = http_get(fhir_url, params, headers)
    response.raise_for_status()
    logger.info("get_fhir_resource successfully fetched capabilitystatement.")
    return response.json()


@lru_cache(maxsize=128)
def get_capability_statement(fhir_base_url: str) -> Dict[str, Any]:
    fhir_metadata_url: str = f"{fhir_base_url}/metadata?_format=json"
    return get_fhir_resource(fhir_metadata_url)


def trim_resource(operations: List[Dict[str, Any]]) -> List[Dict[str, Optional[str]]]:
    logger.debug(f"trim_resource called with {len(operations)} operations.")
    trimmed = [
        {"name": operation.get("name"), "documentation": operation.get("documentation")}
        for operation in operations
        if "name" in operation or "documentation" in operation
    ]
    logger.debug(f"trim_resource returning {len(trimmed)} trimmed operations.")
    return trimmed
