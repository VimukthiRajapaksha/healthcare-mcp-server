"""Main entry point for simple MCP server with GitHub OAuth authentication."""

import sys
from server import main
import logging

# Configure logging for the application
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s {%(name)s.%(funcName)s:%(lineno)d} - %(message)s",
)

sys.exit(main())
