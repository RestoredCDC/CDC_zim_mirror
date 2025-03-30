"""
Utilities for the webpage comparison feature.

Handles the heavy lifting of fetching web pages (using Playwright for
dynamic JS-heavy sites) and doing initial text extraction/normalization.
Designed to be called concurrently.
"""

import logging
import os
from typing import List, Set

from inscriptis import get_text
from playwright.sync_api import (
    Error as PlaywrightError,
    Route,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

# --- Configuration Constants ---
# These drive how Playwright behaves during fetching.
# Might move to a central config.py if used elsewhere later.

# Playwright Settings
BROWSER_TYPE: str = os.environ.get(
    "PW_BROWSER_TYPE", "chromium"
)  # Browser to use (chromium, firefox, webkit)
HEADLESS_MODE: bool = (
    os.environ.get("PW_HEADLESS", "true").lower() == "true"
)  # Run browser without UI? Default true.
# Timeouts in milliseconds
PLAYWRIGHT_TIMEOUT: int = int(
    os.environ.get("PW_TIMEOUT", 20000)
)  # Max time for page.goto() overall (20s)
NETWORK_IDLE_TIMEOUT: int = int(
    os.environ.get("PW_IDLE_TIMEOUT", 3000)
)  # Max time to wait for network quiet after load (3s)
PAGE_LOAD_WAIT_UNTIL: str = (
    "load"  # Default 'load' event seems reliable enough for initial nav success
)

# Resource Blocking Settings - Skip common cruft for faster loads
BLOCK_RESOURCE_TYPES: Set[str] = {
    "image",
    "font",
    "media",
    "stylesheet",
}  # Stylesheets blocked too, check if needed
BLOCK_URL_SUBSTRINGS: Set[str] = {
    # Common analytics, ads, trackers
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "ads.",
    "adservice.",
    "adsystem.",
    "/ads?",
    "/adserver?",
    "/track?",
}

# General Fetch Settings
MAX_CONTENT_SIZE: int = (
    10 * 1024 * 1024
)  # 10MB limit for rendered HTML source to prevent memory issues
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36 WebDifferTool/2.0"  # Generic-ish UA
)
# --- End Configuration ---

# Logger for functions in this module
module_logger = logging.getLogger(__name__)


def _handle_route(route: Route, logger: logging.Logger):
    """
    Playwright route handler. Blocks requests based on type or URL substring.
    This speeds up page loading significantly by skipping non-essential assets.
    Called for *every* request the page tries to make.
    """
    should_block = False
    resource_type = route.request.resource_type
    request_url = route.request.url

    # Check if type or URL substring matches our blocklists
    if resource_type in BLOCK_RESOURCE_TYPES:
        should_block = True
    elif any(sub in request_url for sub in BLOCK_URL_SUBSTRINGS):
        should_block = True

    # Abort or continue the request
    if should_block:
        logger.debug(f"Blocking [{resource_type}]: {request_url}")
        try:
            route.abort()
        except PlaywrightError as e:  # Don't crash if abort fails (rare)
            logger.warning(f"Ignoring error aborting route {request_url}: {e}")
    else:
        try:
            route.continue_()
        except PlaywrightError as e:  # Don't crash if continue fails (rare)
            logger.warning(f"Ignoring error continuing route {request_url}: {e}")


def fetch_and_process_url(url: str) -> str:
    """
    Fetches a URL using a headless browser (Playwright), attempts to block
    unnecessary resources, waits for network activity to settle slightly,
    then extracts readable text using Inscriptis.

    This handles dynamic JS rendering better than a simple requests.get().
    Designed to be run in a separate thread/process.

    Args:
        url: The URL to fetch and process.

    Returns:
        The processed text content as a string on success.
        An error message string starting with "Error:" on failure.
    """
    fetch_logger = logging.getLogger(
        __name__ + ".fetch_thread"
    )  # Separate logger for thread context
    fetch_logger.info(f"Starting fetch for: {url}")

    browser = None
    context = None
    page = None

    try:
        # Using sync_playwright() context manager handles setup/teardown
        with sync_playwright() as p:
            try:
                fetch_logger.info(f"Launching {BROWSER_TYPE}...")
                browser = p[BROWSER_TYPE].launch(headless=HEADLESS_MODE)
                context = browser.new_context(user_agent=DEFAULT_USER_AGENT)
                page = context.new_page()

                # Set up resource blocking before navigation
                fetch_logger.info("Enabling request interception...")
                page.route("**/*", lambda route: _handle_route(route, fetch_logger))

                fetch_logger.info(f"Navigating to {url}...")
                response = None
                try:
                    # Main navigation action
                    response = page.goto(
                        url, timeout=PLAYWRIGHT_TIMEOUT, wait_until=PAGE_LOAD_WAIT_UNTIL
                    )
                except PlaywrightTimeoutError:
                    fetch_logger.error(
                        f"Navigation timeout after {PLAYWRIGHT_TIMEOUT}ms for {url}"
                    )
                    return f"Error: Page load timed out after {PLAYWRIGHT_TIMEOUT // 1000}s for {url}"
                except PlaywrightError as e:
                    # Catch specific Playwright/network errors during navigation
                    fetch_logger.error(f"Navigation error for {url}: {e}")
                    err_msg = str(e).splitlines()[0]
                    if "net::ERR_NAME_NOT_RESOLVED" in str(e):
                        return f"Error: Could not resolve hostname for {url}"
                    if "net::ERR_CONNECTION_REFUSED" in str(e):
                        return f"Error: Connection refused for {url}"
                    return f"Error: Browser navigation error for {url}: {err_msg}"
                except Exception as e:  # Catch unexpected errors during goto
                    fetch_logger.error(
                        f"Unexpected navigation error for {url}", exc_info=True
                    )
                    # Return type name only, avoid leaking too much detail in error string
                    return f"Error: Unexpected navigation error for {url}: {type(e).__name__}"

                # Sanity check response object
                if response is None:
                    fetch_logger.error(f"Failed to get response object for {url}")
                    return f"Error: Browser failed to get response for {url}"

                # Check HTTP status code
                status_code = response.status
                fetch_logger.info(f"Got Status {status_code} for {url}")
                if status_code < 200 or status_code >= 400:
                    # Use status_text if available, otherwise just the code
                    reason = (
                        f". Reason: {response.status_text}"
                        if response.status_text
                        else ""
                    )
                    return f"Error: HTTP Error {status_code} for {url}{reason}"

                # Wait briefly for network activity to hopefully finish after 'load' event
                # Helps catch content loaded by JS shortly after initial load.
                try:
                    fetch_logger.info(
                        f"Waiting for network idle ({NETWORK_IDLE_TIMEOUT}ms max)..."
                    )
                    page.wait_for_load_state(
                        "networkidle", timeout=NETWORK_IDLE_TIMEOUT
                    )
                    fetch_logger.info("Network appears idle.")
                except (
                    PlaywrightTimeoutError
                ):  # It's okay if it times out, proceed anyway
                    fetch_logger.warning(
                        f"Network idle timeout hit for {url}. Proceeding."
                    )
                except (
                    PlaywrightError
                ) as e:  # Other errors during wait? Log and proceed.
                    fetch_logger.warning(
                        f"Error waiting for network idle for {url}: {e}. Proceeding."
                    )

                # Get the final rendered HTML
                fetch_logger.info("Extracting final HTML content...")
                try:
                    final_html = page.content()
                except Exception as e:
                    fetch_logger.error(
                        f"Failed to get page content for {url}", exc_info=True
                    )
                    return f"Error: Failed to extract rendered HTML from {url}: {type(e).__name__}"

                # Check size limit before processing further
                content_bytes_len = len(final_html.encode("utf-8", errors="replace"))
                fetch_logger.info(f"HTML content size: {content_bytes_len} bytes")
                if content_bytes_len > MAX_CONTENT_SIZE:
                    return f"Error: Rendered content exceeds size limit ({MAX_CONTENT_SIZE // (1024*1024)}MB) for {url}."

                # Convert HTML to plain text using Inscriptis
                fetch_logger.info("Converting HTML to text via Inscriptis...")
                try:
                    # Inscriptis does a decent job of preserving structure for diffing
                    processed_text = get_text(final_html)
                    fetch_logger.info(f"Successfully fetched and processed {url}")
                    return processed_text
                except Exception as e:
                    fetch_logger.error(
                        f"Inscriptis conversion failed for {url}", exc_info=True
                    )
                    return f"Error: Failed to convert HTML to text for {url}: {type(e).__name__}"

            finally:
                # Ensure browser resources are closed even if errors occur
                fetch_logger.debug(f"Cleaning up Playwright resources for {url}")
                if page:
                    try:
                        page.close()
                    except Exception as e:
                        fetch_logger.error(f"Error closing page for {url}: {e}")
                if context:
                    try:
                        context.close()
                    except Exception as e:
                        fetch_logger.error(f"Error closing context for {url}: {e}")
                if browser:
                    try:
                        browser.close()
                    except Exception as e:
                        fetch_logger.error(f"Error closing browser for {url}: {e}")

    except PlaywrightError as e:
        # Catch errors during Playwright setup (e.g., browser install issues)
        fetch_logger.error(
            f"General Playwright setup error for {url}: {e}", exc_info=True
        )
        return (
            f"Error: Browser automation setup error for {url}: {str(e).splitlines()[0]}"
        )
    except Exception as e:
        # Catch any other unexpected errors
        fetch_logger.error(f"Unexpected outer error processing {url}", exc_info=True)
        return f"Error: Unexpected error processing {url}: {type(e).__name__}"


def normalize_whitespace(text_lines: List[str]) -> List[str]:
    """
    Simple helper to strip leading/trailing whitespace from each line in a list.
    Used before diffing so whitespace-only changes are ignored.
    """
    if not isinstance(text_lines, list):
        module_logger.warning("normalize_whitespace received non-list input.")
        return []
    # Creates a new list using list comprehension
    return [line.strip() for line in text_lines]
