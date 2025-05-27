# FHIR Resource Search Tool

## Project Overview

This command-line tool allows you to search for FHIR (Fast Healthcare Interoperability Resources) resources on a specified FHIR server. It takes a resource type (e.g., `Patient`, `Observation`) as a command-line argument and search parameters as a JSON string via stdin. The tool then queries the configured FHIR server and outputs the raw JSON response.

It is built with Python and uses `requests` for HTTP communication and `python-dotenv` for environment variable management. Dependencies are managed using `uv`.

## Prerequisites

- Python 3.8+
- `uv` (for package management, can be installed with `pip install uv`)
- An accessible FHIR server (defaults to the public HAPI FHIR test server).

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

2.  **Create a virtual environment and install dependencies:**
    This project uses `uv` for dependency management.
    ```bash
    # Create a virtual environment (e.g., in a .venv directory)
    uv venv
    # Activate the virtual environment
    # On macOS/Linux:
    source .venv/bin/activate
    # On Windows (PowerShell):
    # .\.venv\Scripts\Activate.ps1
    # On Windows (CMD):
    # .\.venv\Scripts\activate.bat

    # Install dependencies from pyproject.toml
    uv pip sync
    ```
    If you prefer to use `pip` with a `requirements.txt` file (you'll need to generate it first if not provided, e.g., `uv pip freeze > requirements.txt`):
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows use `\.venv\Scripts\activate`
    pip install -r requirements.txt
    ```

3.  **Configure Environment Variables:**
    The tool uses a `.env` file to manage environment variables. Copy the example file and customize it if needed:
    ```bash
    cp .env.example .env
    ```
    The primary variable is `FHIR_BASE_URL`:
    ```env
    # .env
    # This is the base URL of the FHIR server to query.
    # It defaults to the HAPI FHIR public test server if not set.
    FHIR_BASE_URL="https://hapi.fhir.org/baseR4"

    # Example for a different server:
    # FHIR_BASE_URL="https://your.fhir.server.com/baseR4"
    ```
    This variable is loaded by `src/main.py` and `src/fhir_client.py`.

## Usage

The tool is run from the command line, providing the `resourceType` as an argument and the `searchParams` as a JSON string through standard input.

**Syntax:**

```bash
python src/main.py <resourceType>
```

After executing the command, the script will wait for you to input the JSON for `searchParams`. Paste or type the JSON, then press:
*   `Ctrl+D` (on Linux/macOS)
*   `Ctrl+Z` then `Enter` (on Windows)
to signal the end of input.

**Output Format:**
The tool will print the raw JSON response received from the FHIR server, pretty-printed with an indent of 4 spaces.

**Example 1: Search for Patient resources**

1.  Run the script for `Patient` resource type:
    ```bash
    python src/main.py Patient
    ```

2.  When prompted, input the following JSON for `searchParams`:
    ```json
    {
      "family": "Smith",
      "_count": "5"
    }
    ```
    This will search for patients with the family name "Smith" and limit the results to 5.

**Example 2: Search for Observation resources for a specific patient**

1.  Run the script for `Observation` resource type:
    ```bash
    python src/main.py Observation
    ```

2.  Input the following JSON for `searchParams`:
    ```json
    {
      "subject": "Patient/12345",
      "code": "http://loinc.org|8302-2",
      "_sort": "-date",
      "_count": "1"
    }
    ```
    This searches for body height observations (LOINC code 8302-2) for the patient with ID `12345`, sorts them by date descending, and returns the latest one.

**Understanding `searchParams`:**
The structure and available parameters for `searchParams` are defined by the FHIR specification for each resource type and the capabilities of the target FHIR server.
*   For general FHIR search parameters: [FHIR Search Documentation](https://www.hl7.org/fhir/search.html)
*   For specific resource types (e.g., `Patient`, `Observation`), refer to their respective pages on the HL7 FHIR specification website (e.g., `https://www.hl7.org/fhir/patient.html#search`).

## Development

### Dependencies
Dependencies are managed with `uv` and are listed in `pyproject.toml`.
*   To add a new runtime dependency: `uv add <package_name>`
*   To add a new development dependency: `uv add <package_name> --dev`
*   To install/update all dependencies: `uv pip sync`

### Logging
The tool uses structured logging. Logs are printed to `stdout` and include timestamps, log levels, and messages, providing insights into the operations being performed.

### Error Handling
*   The script will exit with a non-zero status code if errors occur.
*   Errors from network requests (e.g., connection issues, timeouts), JSON parsing, or invalid responses from the FHIR server (e.g., 4xx/5xx status codes) are logged to `stderr`.

## IDE Integration

### VS Code

1.  **Interpreter:** Open the project folder in VS Code. If you created a `.venv` in the project root, VS Code should automatically detect and suggest using it. If not, open the Command Palette (`Ctrl+Shift+P` or `Cmd+Shift+P`), type "Python: Select Interpreter", and choose the Python interpreter located in your `.venv/bin/` (or `.venv\Scripts\` on Windows) directory.
2.  **Environment Variables:** VS Code can load environment variables from the `.env` file for debugging sessions. Ensure the Python extension is configured to do so (this is often the default). You can also set them in a `launch.json` configuration.
3.  **Launch Configuration (for debugging with stdin):**
    Debugging scripts that require stdin can be tricky. One way is to modify `src/main.py` temporarily to read from a file if stdin is empty, or use VS Code's `launch.json` to simulate stdin (though direct stdin input is not well supported for Python debugging in VS Code's default debugger).
    A simpler approach for testing is often to use the terminal as described in the "Usage" section.
    For more complex debugging involving stdin, you might use a `launch.json` like this, which requires you to have a file (e.g., `input.json`) with your test JSON:
    ```json
    // .vscode/launch.json
    {
        "version": "0.2.0",
        "configurations": [
            {
                "name": "Python: FHIR Search Tool",
                "type": "python",
                "request": "launch",
                "program": "${workspaceFolder}/src/main.py",
                "args": ["Patient"], // Replace "Patient" with the resourceType you want to test
                "console": "integratedTerminal",
                // "internalConsoleOptions": "neverOpen", // if you prefer only the integrated terminal
                // To simulate stdin, you might need to use shell redirection
                // if your debugger/terminal supports it, or adapt main.py
                // For example, if using a shell that supports redirection:
                // "args": ["Patient", "<", "input.json"] // This specific syntax might not work directly in launch.json args
                                                        // but illustrates the concept.
                                                        // A more robust way is to modify main.py for debugging.
            }
        ]
    }
    ```
    Given the direct stdin requirement, running and testing from the integrated terminal is usually most straightforward.

### Claude Desktop (or other similar environments)

1.  **Interpreter:** Ensure your development environment is configured to use the Python interpreter from the virtual environment (`.venv/bin/python`).
2.  **Environment Variables:** The `python-dotenv` library will automatically load variables from the `.env` file when the script runs, so ensure the `.env` file is in the root directory from where you execute the script.
3.  **Execution:** Run the tool from the terminal as described in the "Usage" section.

## Docker (Optional)

A `Dockerfile` is provided to build a container image for this tool.

1.  **Build the image:**
    ```bash
    docker build -t fhir-search-tool .
    ```

2.  **Run the container:**
    You'll need to pass the `resourceType` and provide the JSON `searchParams` via stdin to the `docker run` command. You can also pass environment variables.
    ```bash
    # Example: Search for Patients with family name "Smith"
    # Note: Use `echo` and a pipe for stdin, or run interactively (`-i`).
    echo '{"family": "Smith"}' | docker run -i --rm \
        -e FHIR_BASE_URL="https://hapi.fhir.org/baseR4" \
        fhir-search-tool Patient
    ```
    Or interactively:
    ```bash
    docker run -i --rm \
        -e FHIR_BASE_URL="https://hapi.fhir.org/baseR4" \
        fhir-search-tool Patient
    # Then paste your JSON and press Ctrl+D
    ```

## Running Tests

(Test setup and commands will be added here once tests are implemented.)

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue.
Ensure your contributions include relevant documentation updates and, if applicable, tests.
