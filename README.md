# Model Context Protocol (MCP) Server for Healthcare

## Overview

This server allows you to search for FHIR (Fast Healthcare Interoperability Resources) resources on a specified FHIR server. It is built with Python and supports command-line, Docker, and VS Code integration.

## Prerequisites
- Python 3.8+
- [uv](https://github.com/astral-sh/uv) (for dependency management)
- An accessible FHIR server (defaults to the public HAPI FHIR test server)

## Setup

1. **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```
2. **Create a virtual environment and install dependencies:**
    ```bash
    uv venv
    source .venv/bin/activate
    uv pip sync requirements.txt
    ```
    Or with pip:
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```
3. **Configure Environment Variables:**
    Copy the example file and customize if needed:
    ```bash
    cp .env.example .env
    ```
    Set `FHIR_BASE_URL` in your `.env` file.

## Usage

Run the server in the MCP Inspector mode:
```bash
mcp dev server.py
```

## VS Code Integration
Add the following JSON block to your User Settings (JSON) file in VS Code. You can do this by pressing Ctrl + Shift + P and typing Preferences: Open User Settings (JSON).

```json
"mcp": {
    "servers": {
        "healthcare": {
            "command": "uv",
            "args": [
                "run",
                "--with",
                "mcp[cli]",
                "--with",
                "requests",
                "mcp",
                "run",
                "ABSOLUTE PATH TO YOUR SERVER.PY FILE"
            ],
            "env": {
                "FHIR_BASE_URL": "https://hapi.fhir.org/baseR4"
            }
        }
    }
}
```

## Example Prompts
- Get allergy history for patient 53373
- Fetch the immunization records for patient ID 53373
- List all active care plans for patient 22
- Provide a consolidated report for patient 53373 that includes their complete allergy history as well as all available immunization records, organized by date and highlighting any critical alerts
- Retrieve all active care plans for patient ID 22 and present them in a markdown table showing each plan’s ID, title, status, intent, and start date
