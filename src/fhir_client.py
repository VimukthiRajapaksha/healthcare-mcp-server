import os
import logging
import requests
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

FHIR_BASE_URL = os.getenv("FHIR_BASE_URL", "https://hapi.fhir.org/baseR4")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def search_fhir_resources(resource_type: str, search_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Searches FHIR resources.

    Args:
        resource_type: The type of FHIR resource to search (e.g., "Patient", "Observation").
        search_params: A dictionary of search parameters.

    Returns:
        The raw JSON response from the FHIR server as a dictionary.

    Raises:
        requests.exceptions.RequestException: For network issues (e.g., connection error, timeout).
        requests.exceptions.HTTPError: For non-200 HTTP status codes from the server.
        ValueError: If the server response is not valid JSON.
    """
    url = f"{FHIR_BASE_URL}/{resource_type}"
    logger.info(f"Requesting FHIR resource: {url} with params: {search_params}")

    try:
        response = requests.get(url, params=search_params)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4XX or 5XX)
        logger.info(f"Successfully fetched FHIR resource: {resource_type}")
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error occurred: {http_err} - {response.text}")
        raise
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Request exception occurred: {req_err}")
        raise
    except ValueError as json_err: # If response.json() fails
        logger.error(f"JSON decoding error: {json_err} - Response text: {response.text}")
        raise ValueError(f"JSON decoding error: {json_err} - Response text: {response.text}") from json_err
