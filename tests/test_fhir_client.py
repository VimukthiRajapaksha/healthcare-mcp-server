import pytest
import requests
import os
from unittest.mock import patch, MagicMock

# Import the function to be tested and the FHIR_BASE_URL
from src.fhir_client import search_fhir_resources, FHIR_BASE_URL as DEFAULT_FHIR_BASE_URL

# Test data
MOCK_PATIENT_RESPONSE = {"resourceType": "Bundle", "entry": [{"resource": {"resourceType": "Patient", "id": "123"}}]}
MOCK_OBSERVATION_RESPONSE = {"resourceType": "Bundle", "entry": [{"resource": {"resourceType": "Observation", "id": "456"}}]}

@pytest.fixture
def mock_env_url(monkeypatch):
    """Fixture to temporarily set FHIR_BASE_URL environment variable."""
    def _set_url(url):
        monkeypatch.setenv("FHIR_BASE_URL", url)
        # Need to reload fhir_client to make it pick up the new env var for its global FHIR_BASE_URL
        # This is a bit tricky as the module is already imported.
        # A more robust way would be to make FHIR_BASE_URL a parameter or class member
        # For this specific structure, we might need to patch the FHIR_BASE_URL constant directly in the module.
        monkeypatch.setattr('src.fhir_client.FHIR_BASE_URL', url)
        return url
    return _set_url

def test_search_fhir_resources_success_patient_no_params(mocker):
    """Test successful API call for Patient resource with no search parameters."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = MOCK_PATIENT_RESPONSE
    
    mock_get = mocker.patch('requests.get', return_value=mock_response)
    
    result = search_fhir_resources("Patient", {})
    
    mock_get.assert_called_once_with(f"{DEFAULT_FHIR_BASE_URL}/Patient", params={})
    assert result == MOCK_PATIENT_RESPONSE

def test_search_fhir_resources_success_observation_with_params(mocker):
    """Test successful API call for Observation resource with search parameters."""
    search_params = {"subject": "Patient/123", "code": "12345-6"}
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = MOCK_OBSERVATION_RESPONSE
    
    mock_get = mocker.patch('requests.get', return_value=mock_response)
    
    result = search_fhir_resources("Observation", search_params)
    
    mock_get.assert_called_once_with(f"{DEFAULT_FHIR_BASE_URL}/Observation", params=search_params)
    assert result == MOCK_OBSERVATION_RESPONSE

def test_search_fhir_resources_override_base_url(mocker, mock_env_url):
    """Test successful API call with overridden FHIR_BASE_URL."""
    custom_url = "https://custom.fhir.server/api"
    # We use mock_env_url to set the environment variable AND patch the module-level constant
    effective_url = mock_env_url(custom_url)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = MOCK_PATIENT_RESPONSE
    
    mock_get = mocker.patch('requests.get', return_value=mock_response)
    
    # Ensure fhir_client is reloaded or its FHIR_BASE_URL is patched if it's read at import time
    # The mock_env_url fixture now handles patching src.fhir_client.FHIR_BASE_URL
    
    result = search_fhir_resources("Patient", {})
    
    mock_get.assert_called_once_with(f"{effective_url}/Patient", params={})
    assert result == MOCK_PATIENT_RESPONSE
    # Important: Reset the FHIR_BASE_URL in fhir_client to avoid affecting other tests
    # This is tricky due to Python's module caching.
    # The mock_env_url fixture with monkeypatch handles this by design for the duration of the test.
    # Alternatively, if FHIR_BASE_URL was a function arg or class member, this would be cleaner.
    # For this structure, monkeypatch.setattr in the fixture is the way.


def test_search_fhir_resources_http_error_404(mocker):
    """Test API call resulting in an HTTP 404 error."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not Found"
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Client Error: Not Found for url")
    
    mock_get = mocker.patch('requests.get', return_value=mock_response)
    
    with pytest.raises(requests.exceptions.HTTPError):
        search_fhir_resources("Patient", {"_id": "nonexistent"})
        
    mock_get.assert_called_once_with(f"{DEFAULT_FHIR_BASE_URL}/Patient", params={"_id": "nonexistent"})

def test_search_fhir_resources_http_error_500(mocker):
    """Test API call resulting in an HTTP 500 error."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Server Error"
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error: Internal Server Error for url")

    mock_get = mocker.patch('requests.get', return_value=mock_response)

    with pytest.raises(requests.exceptions.HTTPError):
        search_fhir_resources("Observation", {})

    mock_get.assert_called_once_with(f"{DEFAULT_FHIR_BASE_URL}/Observation", params={})

def test_search_fhir_resources_network_error(mocker):
    """Test API call resulting in a network error (ConnectionError)."""
    mock_get = mocker.patch('requests.get', side_effect=requests.exceptions.ConnectionError("Failed to connect"))
    
    with pytest.raises(requests.exceptions.RequestException): # ConnectionError is a subclass of RequestException
        search_fhir_resources("Patient", {})
        
    mock_get.assert_called_once_with(f"{DEFAULT_FHIR_BASE_URL}/Patient", params={})

def test_search_fhir_resources_invalid_json_response(mocker):
    """Test API call with a response that is not valid JSON."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "This is not JSON"
    # Simulate json.decoder.JSONDecodeError by having .json() raise ValueError, as requests.json() does
    mock_response.json.side_effect = ValueError("Decoding JSON has failed") # requests.json() raises requests.exceptions.JSONDecodeError, which is a subclass of ValueError
    
    mock_get = mocker.patch('requests.get', return_value=mock_response)
    
    with pytest.raises(ValueError) as excinfo: # Expecting the ValueError we raise from fhir_client
        search_fhir_resources("Patient", {})
    
    assert "JSON decoding error" in str(excinfo.value)
    mock_get.assert_called_once_with(f"{DEFAULT_FHIR_BASE_URL}/Patient", params={})

# To ensure the FHIR_BASE_URL is reset for other test files if not using monkeypatch fixture for all URL tests
@pytest.fixture(autouse=True)
def reset_fhir_base_url(monkeypatch):
    """Ensure FHIR_BASE_URL is reset after each test if it was patched."""
    original_url = DEFAULT_FHIR_BASE_URL # Capture at import time
    yield
    monkeypatch.setattr('src.fhir_client.FHIR_BASE_URL', original_url)

# Note: Tests for main.py are not included here as per the subtask's optional guidance.
# Focusing on robust unit tests for fhir_client.py.
# tests/__init__.py should be present (created in earlier step).
# pyproject.toml typically doesn't need specific pytest config for test discovery if using standard layout.
# Running tests with `uv run pytest` will be the final step.
