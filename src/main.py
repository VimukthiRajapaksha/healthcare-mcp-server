import argparse
import json
import logging
import sys
from typing import Dict, Any
from dotenv import load_dotenv

from fhir_client import search_fhir_resources, FHIR_BASE_URL # Assuming fhir_client.py is in the same directory

# Load environment variables from .env file
load_dotenv()

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def main():
    """
    Main function to parse arguments, search FHIR resources, and print the response.
    """
    parser = argparse.ArgumentParser(description="FHIR Resource Search Tool")
    parser.add_argument(
        "resourceType",
        type=str,
        help="The type of FHIR resource to search (e.g., Patient, Observation)."
    )
    # searchParams will be read from stdin

    args = parser.parse_args()

    logger.info(f"FHIR base URL in use: {FHIR_BASE_URL}")
    logger.info(f"Received resourceType: {args.resourceType}")

    try:
        search_params_json = sys.stdin.read()
        if not search_params_json:
            logger.warning("No search parameters provided via stdin.")
            search_params: Dict[str, Any] = {}
        else:
            logger.info(f"Received searchParams (raw JSON string from stdin): {search_params_json.strip()}")
            search_params = json.loads(search_params_json)
        logger.info(f"Parsed searchParams: {search_params}")

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from stdin: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred while reading or parsing stdin: {e}")
        sys.exit(1)

    try:
        logger.info(f"Searching for resource type '{args.resourceType}' with parameters: {search_params}")
        results = search_fhir_resources(args.resourceType, search_params)
        # Pretty print the JSON output
        print(json.dumps(results, indent=4))
        logger.info(f"Successfully retrieved and printed FHIR resources for {args.resourceType}")

    except requests.exceptions.RequestException as e:
        logger.error(f"Error during FHIR resource search: {e}")
        sys.exit(1)
    except ValueError as e: # Catching potential JSON decoding errors from fhir_client
        logger.error(f"Error processing response from FHIR server: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
