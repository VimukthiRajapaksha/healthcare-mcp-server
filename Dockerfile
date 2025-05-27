# 1. Choose a suitable Python base image
# Using python:3.11-slim as it's a good balance of size and functionality.
FROM python:3.11-slim

# 2. Set up the working directory
# All subsequent commands will be run from this directory.
WORKDIR /app

# 3. Install uv
# We'll use pip to install uv, which will then be used for dependency management.
# This ensures we're using the specific `uv` version if needed and keeps build consistent.
# Using --no-cache-dir to keep the image layer smaller.
RUN pip install --no-cache-dir uv

# 4. Copy dependency definition files
# Copy pyproject.toml first. uv uses this to understand project metadata and dependencies.
# If a uv.lock file were standard and committed, it would be copied here too.
COPY pyproject.toml pyproject.toml

# 5. Install dependencies using uv
# `uv pip install .` reads pyproject.toml, resolves dependencies, and installs them.
# `--system` installs packages into the system Python environment, which is common for containers.
# `--no-cache` (uv's equivalent to pip's --no-cache-dir for downloads) helps keep image size down.
# This command installs the package defined by pyproject.toml (our app) and its dependencies.
RUN uv pip install --system --no-cache .

# 6. Copy the application source code
# This copies the 'src' directory from the build context into the container at /app/src.
COPY src/ src/

# 7. Set environment variables (Optional but recommended for documentation)
# FHIR_BASE_URL can be overridden at runtime using `docker run -e FHIR_BASE_URL=...`.
# Setting a default here can be useful if there's a common public endpoint.
# However, for this tool, the default is already handled in the Python code
# (falling back to hapi.fhir.org/baseR4 if the env var is not set).
# So, explicitly setting it here is more for documentation or if a different default was desired for the container.
# ENV FHIR_BASE_URL="https://hapi.fhir.org/baseR4"

# 8. Define the entrypoint
# This specifies the command that will be run when the container starts.
# We use `python src/main.py`. The script `src/main.py` is designed to take
# <resourceType> as a command-line argument and JSON search parameters from stdin.
ENTRYPOINT ["python", "src/main.py"]

# CMD can provide default arguments to the ENTRYPOINT.
# Since <resourceType> is a mandatory argument for src/main.py and varies with each run,
# it's best left for the user to provide when running the container.
# e.g., `docker run fhir-search-tool Patient`
# If a default CMD was provided, e.g., CMD ["Patient"], then `docker run fhir-search-tool`
# would automatically search for "Patient". This is not the desired behavior here.

# Comments have been added throughout this Dockerfile.
# README.md instructions for Docker build and run were addressed in a previous step
# and should be double-checked.
# No ports need to be exposed as this is a command-line tool, not a server.
