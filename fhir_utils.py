import aiohttp
import httpx
from fhirpy import AsyncFHIRClient

from oauth.types import FHIROAuthConfigs


async def create_async_fhir_client(
    config: FHIROAuthConfigs,
    access_token: str,
    extra_headers: dict | None = None,
) -> AsyncFHIRClient:
    """Create a FHIR AsyncClient with defaults."""

    client: AsyncFHIRClient = AsyncFHIRClient(
        url = config.base_url,
        authorization=f"Bearer {access_token}",
        aiohttp_config={
            "timeout": aiohttp.ClientTimeout(total=config.timeout),
        },
        extra_headers=extra_headers,
    )

    return client


async def get_operation_outcome_exception() -> dict:
    return {
        "resourceType": "OperationOutcome",
        "issue": [
            {
                "severity": "error",
                "code": "exception",
                "diagnostics": "An unexpected internal error has occurred.",
            }
        ],
    }


async def get_operation_outcome_required_error(element: str = "") -> dict:
    return {
        "resourceType": "OperationOutcome",
        "issue": [
            {
                "severity": "error",
                "code": "required",
                "diagnostics": f"A required element {element} is missing.",
            }
        ],
    }
