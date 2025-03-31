"""
Core logic for processing a comparison request.

Takes two URLs, validates them, fetches them using utils, runs difflib,
and generates the data structure needed by the frontend template/JS.

Note:
  - Playwright must be installed with "playwright install" after installing with pip.
  - Portions of this feature are inspired by changedetection.io
   (https://github.com/changedetectionio/changedetection.io).
"""

import datetime
import concurrent.futures
import difflib
import logging
from typing import Dict, List, Any
from urllib.parse import urlparse

# Use relative import to get fetcher/normalizer
from .compare_utils import fetch_and_process_url, normalize_whitespace

# Logger for this module
module_logger = logging.getLogger(__name__)


def _validate_url(
    url: str,
    allowed_schemes: List[str],
    allowed_hosts: List[str],
    allow_subdomains: bool = False,
) -> bool:
    """
    Internal helper to validate a URL against allowed schemes and hosts.
    Basic defense against SSRF by restricting targets.

    Args:
        url: The URL string to validate.
        allowed_schemes: List of allowed schemes (e.g., ['http', 'https']).
        allowed_hosts: List of exact allowed hostnames (case-insensitive). Include port if needed? No, hostname only.
        allow_subdomains: If True, allows subdomains of the hosts in allowed_hosts (e.g., *.cdc.gov).

    Returns:
        True if the URL is valid, False otherwise.
    """
    try:
        parsed = urlparse(url)
        # Scheme check
        if not parsed.scheme or parsed.scheme.lower() not in allowed_schemes:
            module_logger.warning(
                f"URL validation failed (scheme '{parsed.scheme}' not in {allowed_schemes}): {url}"
            )
            return False
        # Hostname check
        if not parsed.netloc:  # Needs a host part
            module_logger.warning(f"URL validation failed (netloc missing): {url}")
            return False

        hostname = parsed.hostname.lower() if parsed.hostname else ""
        if not hostname:  # Ensure hostname extracted correctly
            module_logger.warning(f"URL validation failed (hostname missing): {url}")
            return False

        # Check against allowed hosts list
        is_allowed_host = False
        for allowed_host in allowed_hosts:
            allowed_host_lower = allowed_host.lower()
            # Exact match
            if hostname == allowed_host_lower:
                is_allowed_host = True
                break
            # Subdomain match (if enabled)
            if allow_subdomains and hostname.endswith(f".{allowed_host_lower}"):
                is_allowed_host = True
                break

        if not is_allowed_host:
            module_logger.warning(
                f"URL validation failed (host '{hostname}' not in allowed list {allowed_hosts}): {url}"
            )
            return False

        # Passed all checks
        return True

    except Exception as e:  # Catch potential errors during parsing
        module_logger.error(f"Error parsing URL during validation: {url} - {e}")
        return False


def get_comparison_data(
    url_a: str,  # Archived URL
    url_b: str,  # Live URL
    expected_archive_host: str,  # Hostname (and optional port) where url_a should live
    logger: logging.Logger,  # Logger passed from Flask route for request context
) -> Dict[str, Any]:
    """
    Validates URLs, fetches them concurrently, performs a diff,
    and returns structured data for the comparison template.

    Args:
        url_a: The URL for the archived version.
        url_b: The URL for the live version (must be cdc.gov).
        expected_archive_host: The hostname:port string url_a must match (from request.host).
        logger: Logger instance for request-specific logging.

    Returns:
        A dictionary containing results:
        {
            "lines_orig_A": List[str], # Original text lines from url_a
            "lines_orig_B": List[str], # Original text lines from url_b
            "render_instructions": List[Dict], # Instructions for frontend JS
            "is_error": bool, # Flag indicating if any error occurred
            "error_msg1": Optional[str], # User-facing error for url_a
            "error_msg2": Optional[str], # User-facing error for url_b
        }
    """
    logger.info(f"Processing comparison: A='{url_a}' B='{url_b}'")

    # --- SSRF Prevention: Validate input URLs before fetching ---
    # Note: expected_archive_host likely includes port (e.g., 127.0.0.1:9090),
    # _validate_url checks hostname part only after splitting.
    allowed_archive_hosts = (
        [expected_archive_host.split(":")[0]] if expected_archive_host else []
    )
    if not _validate_url(url_a, ["http", "https"], allowed_archive_hosts):
        logger.error(f"SSRF Prevented: Invalid archive URL provided: {url_a}")
        # Return error structure immediately
        return {
            "lines_orig_A": [],
            "lines_orig_B": [],
            "render_instructions": [],
            "is_error": True,
            "error_msg1": "Error: Invalid or disallowed URL for archived content.",
            "error_msg2": None,
        }

    # url_b MUST be https and *.cdc.gov
    if not _validate_url(url_b, ["https"], ["cdc.gov"], allow_subdomains=True):
        logger.error(f"SSRF Prevented: Invalid live URL provided: {url_b}")
        return {
            "lines_orig_A": [],
            "lines_orig_B": [],
            "render_instructions": [],
            "is_error": True,
            "error_msg1": None,
            "error_msg2": "Error: Invalid or disallowed URL for live content (must be cdc.gov).",
        }
    # --- End Validation ---

    logger.info("URL validation passed.")

    # Initialize result variables
    text_orig_A = f"Error: Fetch not completed for {url_a}"
    text_orig_B = f"Error: Fetch not completed for {url_b}"
    is_error = False
    error_msg1 = None
    error_msg2 = None
    lines_orig_A = []
    lines_orig_B = []
    render_instructions = []

    # --- Parallel Fetching using the utility function ---
    logger.debug(f"Starting parallel fetch.")
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="CompareFetch"
    ) as executor:
        future1 = executor.submit(fetch_and_process_url, url_a)
        future2 = executor.submit(fetch_and_process_url, url_b)

        # Retrieve results, logging any exceptions from the threads
        try:
            text_orig_A = future1.result()
        except Exception as e:
            logger.error(
                f"Fetch thread A ({url_a}) raised exception: {e}", exc_info=True
            )
            text_orig_A = (
                f"Error: Fetch failed for {url_a}. See server logs."  # Generic message
            )
        try:
            text_orig_B = future2.result()
        except Exception as e:
            logger.error(
                f"Fetch thread B ({url_b}) raised exception: {e}", exc_info=True
            )
            text_orig_B = (
                f"Error: Fetch failed for {url_b}. See server logs."  # Generic message
            )

    logger.info("Parallel fetch finished.")
    # --- End Parallel Fetching ---

    # Check if the fetch functions returned error strings
    if isinstance(text_orig_A, str) and text_orig_A.startswith("Error:"):
        is_error = True
        error_msg1 = text_orig_A  # Use the (now generic) message from fetcher
        logger.error(f"Fetch Error A ({url_a}): {text_orig_A}")
    if isinstance(text_orig_B, str) and text_orig_B.startswith("Error:"):
        is_error = True
        error_msg2 = text_orig_B  # Use the (now generic) message from fetcher
        logger.error(f"Fetch Error B ({url_b}): {text_orig_B}")

    # Proceed with diffing only if fetching succeeded
    if not is_error:
        try:
            logger.debug("Splitting fetched text into lines.")
            lines_orig_A = text_orig_A.splitlines()
            lines_orig_B = text_orig_B.splitlines()

            logger.debug("Normalizing whitespace for comparison.")
            lines_norm_A = normalize_whitespace(lines_orig_A)
            lines_norm_B = normalize_whitespace(lines_orig_B)

            logger.info("Running difflib SequenceMatcher...")
            matcher = difflib.SequenceMatcher(
                isjunk=None, a=lines_norm_A, b=lines_norm_B, autojunk=False
            )
            opcodes = matcher.get_opcodes()
            logger.info(f"Generated {len(opcodes)} opcodes.")

            # Process opcodes into instructions for the frontend JS rendering
            logger.debug("Generating render instructions from opcodes...")
            for tag, i1, i2, j1, j2 in opcodes:
                if tag == "equal":
                    for k in range(j2 - j1):
                        render_instructions.append(
                            {"type": "unchanged", "line_index_b": j1 + k}
                        )
                elif tag == "delete":
                    for k in range(i2 - i1):
                        render_instructions.append(
                            {"type": "removed", "line_index_a": i1 + k}
                        )
                elif tag == "insert":
                    for k in range(j2 - j1):
                        render_instructions.append(
                            {"type": "added", "line_index_b": j1 + k}
                        )
                elif tag == "replace":
                    n_removed, n_added = i2 - i1, j2 - j1
                    for k in range(min(n_removed, n_added)):
                        render_instructions.append(
                            {
                                "type": "replace",
                                "line_index_a": i1 + k,
                                "line_index_b": j1 + k,
                            }
                        )
                    for k in range(min(n_removed, n_added), n_removed):
                        render_instructions.append(
                            {"type": "removed", "line_index_a": i1 + k}
                        )
                    for k in range(min(n_removed, n_added), n_added):
                        render_instructions.append(
                            {"type": "added", "line_index_b": j1 + k}
                        )

            logger.info(f"Generated {len(render_instructions)} render instructions.")

        except Exception as proc_e:
            # Catch errors during diff processing
            logger.error(f"Error during diff processing: {proc_e}", exc_info=True)
            is_error = True
            # Set generic error message if no fetch error happened before
            generic_proc_error = "Error: Internal error during comparison processing."
            if not error_msg1:
                error_msg1 = generic_proc_error
            if not error_msg2:
                error_msg2 = generic_proc_error

    # Get current UTC time when processing is essentially complete
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    # Format it into a readable string
    timestamp_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    logger.info(f"Comparison processed at: {timestamp_str}")

    # Always return the structured dictionary
    return {
        "lines_orig_A": lines_orig_A,
        "lines_orig_B": lines_orig_B,
        "render_instructions": render_instructions,
        "is_error": is_error,
        "error_msg1": error_msg1,
        "error_msg2": error_msg2,
        "comparison_timestamp_utc": timestamp_str,
    }
