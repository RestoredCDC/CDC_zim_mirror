"""
Module: compare.py

This module retrieves two HTML pages—one from an archived RestoredCDC page and one from a live CDC page—
and generates an HTML diff of their visible content.

Workflow:
  1. Validate that the provided URLs are from allowed domains.
     (Archived URL must be on restoredcdc.org; live URL must be on cdc.gov.)
  2. Fetch HTML content from the URLs.
     - For pages that are statically served (e.g. restoredcdc.org) we use a standard requests call.
     - For pages that inject content via JavaScript (e.g. cdc.gov) we use Playwright
       to fetch the fully rendered HTML.
  3. Parse and extract the visible text from the HTML while preserving hierarchy:
       - Block-level elements (defined in BLOCK_TAGS) force new lines.
       - Inline elements (like <a>) are merged into their parent text.
  4. Normalize indent levels so that no line is indented more than one level deeper than the previous.
  5. Compute a diff on the extracted text (using difflib) and wrap changes in HTML styling if needed.
  6. Flatten the nested diff groups into final HTML output, where each line is wrapped in a <div>
     with a left margin proportional to its indent level.

Security improvements:
  - Only URLs from allowed domains are accepted.
  - Unwanted strings (e.g. injected JS markers) are filtered out.
  - We use a standard User-Agent header and enforce UTF-8 encoding.
  - For dynamic pages (e.g. cdc.gov), we fetch the rendered HTML using Playwright.

Note:
  - Playwright must be installed with "playwright install" after installing with pip.
  - Portions of this feature are inspired by changedetection.io
   (https://github.com/changedetectionio/changedetection.io).
"""

import difflib
import logging
from typing import List, Iterator, Union
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# Import Playwright's synchronous API for fetching rendered HTML.
from playwright.sync_api import sync_playwright

# CSS styles for diff highlighting (used when html_colour=True)
REMOVED_STYLE = "background-color: #fadad7; color: #b30000;"
ADDED_STYLE = "background-color: #eaf2c2; color: #406619;"

# Block-level tags that force a new line during text extraction.
BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "canvas",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "noscript",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tfoot",
    "ul",
    "video",
    "tr",
    "td",
    "th",
}

# Set up basic logging.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def validate_url(url: str, allowed_domains: List[str]) -> bool:
    """
    Validate that the URL uses http/https and its domain ends with one of the allowed domains.

    Parameters:
        url (str): The URL to validate.
        allowed_domains (List[str]): List of allowed domain substrings (e.g. "restoredcdc.org").

    Returns:
        bool: True if the URL is allowed; False otherwise.
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        logger.error(f"Error parsing URL '{url}': {e}")
        return False

    if parsed.scheme not in ("http", "https"):
        logger.warning(f"URL scheme not allowed: {url}")
        return False

    netloc = parsed.netloc.lower()
    if not any(netloc.endswith(domain.lower()) for domain in allowed_domains):
        logger.warning(f"URL not in allowed domains: {url}")
        return False

    return True

def fetch_rendered_html(url: str) -> str:
    """
    Fetch the fully rendered HTML content from the given URL using Playwright.
    This function launches a headless Chromium browser, navigates to the URL, and returns the page content.

    Parameters:
        url (str): The URL to fetch.

    Returns:
        str: The fully rendered HTML content.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            # Increase timeout if needed; here we set 15 seconds.
            page.goto(url, timeout=15000)
            content = page.content()
            browser.close()
            return content
    except Exception as e:
        logger.error(f"Error fetching rendered HTML from {url}: {e}")
        return ""


def fetch_html(url: str, allowed_domains: List[str]) -> str:
    """
    Fetch HTML content from the provided URL.

    For pages on cdc.gov (which often inject content via JavaScript), use Playwright to
    fetch the rendered HTML. For other pages, use a standard requests call.

    Parameters:
        url (str): The target URL.
        allowed_domains (List[str]): List of allowed domain substrings (e.g. "restoredcdc.org").

    Returns:
        str: The HTML content as a string; empty string on failure.
    """
    if not validate_url(url, allowed_domains):
        logger.error(f"Invalid URL: {url}")
        return ""

    # For cdc.gov pages, we use Playwright to get the dynamic content.
    parsed_url = urlparse(url)
    if parsed_url.hostname and (parsed_url.hostname == "cdc.gov" or parsed_url.hostname.endswith(".cdc.gov")):
        logger.info(f"Fetching rendered HTML for dynamic page: {url}")
        return fetch_rendered_html(url)
    else:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/110.0.0.0 Safari/537.36"
            )
        }
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            response.encoding = "utf-8"
            return response.text
        except requests.RequestException as e:
            logger.error(f"Error fetching {url}: {e}")
            return ""

def process_children(node, current_indent: int) -> List[tuple]:
    """
    Process the children of a BeautifulSoup node and accumulate inline text into a single line.

    Block-level elements trigger a flush of accumulated text and recursive processing with an increased indent.
    Inline elements are merged.

    Parameters:
        node: A BeautifulSoup node whose children will be processed.
        current_indent (int): The current indentation level.

    Returns:
        List[tuple]: List of (indent, text) tuples.
    """
    lines = []
    inline_buffer = ""
    for child in node.children:
        if child.name is None:
            text = " ".join(child.split())
            if text:
                inline_buffer += text + " "
        else:
            if child.name.lower() in BLOCK_TAGS:
                if inline_buffer.strip():
                    lines.append((current_indent, inline_buffer.strip()))
                    inline_buffer = ""
                lines.extend(process_node(child, current_indent + 1))
            else:
                text = " ".join(child.get_text(" ", strip=True).split())
                if text:
                    inline_buffer += text + " "
    if inline_buffer.strip():
        lines.append((current_indent, inline_buffer.strip()))
    return lines


def process_node(node, current_indent: int = 0) -> List[tuple]:
    """
    Recursively process a BeautifulSoup node to extract visible text with hierarchical indent levels.

    For block-level elements, the children are processed with an increased indent.
    Inline elements are merged into the current line.
    If the node is a list item (<li>), the first line is prefixed with "* " to mimic a bullet.

    Parameters:
        node: A BeautifulSoup node.
        current_indent (int): Current indentation level.

    Returns:
        List[tuple]: List of (indent, text) tuples.
    """
    if node.name is None:
        text = " ".join(node.split())
        return [(current_indent, text)] if text else []
    if node.name.lower() in BLOCK_TAGS:
        lines = process_children(node, current_indent)
        if node.name.lower() == "li" and lines:
            indent, text = lines[0]
            lines[0] = (indent, "* " + text)
        return lines
    else:
        return process_children(node, current_indent)


def extract_text_with_indent(html_content: str) -> List[tuple]:
    """
    Extract visible text from HTML content while preserving hierarchical indent levels.

    Inline tags (e.g. <a>) are merged into their parent text. Using the "lxml" parser
    improves our ability to capture dynamically injected content.

    Parameters:
        html_content (str): HTML content to process.

    Returns:
        List[tuple]: List of (indent, text) tuples.
    """
    soup = BeautifulSoup(html_content, "lxml")
    body = soup.body if soup.body else soup
    return process_node(body, 0)


def normalize_indents(lines: List[tuple]) -> List[tuple]:
    """
    Normalize indent levels so that each line's indent is at most one greater than the previous line.
    The first line is forced to indent level 0.

    Parameters:
        lines (List[tuple]): List of (indent, text) tuples.

    Returns:
        List[tuple]: Normalized list of tuples.
    """
    normalized = []
    for i, (indent, text) in enumerate(lines):
        new_indent = 0 if i == 0 else min(indent, normalized[-1][0] + 1)
        normalized.append((new_indent, text))
    return normalized


def slice_range(lst: List[tuple], start: int, end: int) -> List[tuple]:
    """
    Return a slice of the list of (indent, text) tuples.
    If start equals end, return a list containing that single element.

    Parameters:
        lst (List[tuple]): The list to slice.
        start (int): Starting index.
        end (int): Ending index.

    Returns:
        List[tuple]: The sliced portion.
    """
    return lst[start:end] if start != end else [lst[start]]


def tuple_diff(
    before: List[tuple],
    after: List[tuple],
    include_equal: bool = False,
    include_removed: bool = True,
    include_added: bool = True,
    include_replaced: bool = True,
    include_change_type_prefix: bool = True,
    html_colour: bool = False,
) -> Iterator[List[tuple]]:
    """
    Compare two sequences of (indent, text) tuples using difflib.
    Comparison is based solely on the text content.
    Yields groups of tuples representing diff segments.
    Optionally, changes are wrapped in HTML styling.

    Parameters:
        before (List[tuple]): Tuples from the original HTML.
        after (List[tuple]): Tuples from the modified HTML.
        include_equal (bool): Yield equal segments.
        include_removed (bool): Yield removed lines.
        include_added (bool): Yield added lines.
        include_replaced (bool): Yield replaced lines.
        include_change_type_prefix (bool): Prefix changes with markers.
        html_colour (bool): Wrap changes in styled <span> tags if True.

    Yields:
        Iterator[List[tuple]]: Groups of (indent, text) tuples.
    """
    before_text = [t[1] for t in before]
    after_text = [t[1] for t in after]
    matcher = difflib.SequenceMatcher(
        isjunk=lambda x: x in " \t", a=before_text, b=after_text
    )
    for tag, alo, ahi, blo, bhi in matcher.get_opcodes():
        if include_equal and tag == "equal":
            yield before[alo:ahi]
        elif include_removed and tag == "delete":
            if html_colour:
                yield [
                    (t[0], f'<span style="{REMOVED_STYLE}">{t[1]}</span>')
                    for t in slice_range(before, alo, ahi)
                ]
            else:
                yield (
                    [(t[0], f"(removed) {t[1]}") for t in slice_range(before, alo, ahi)]
                    if include_change_type_prefix
                    else slice_range(before, alo, ahi)
                )
        elif include_replaced and tag == "replace":
            if html_colour:
                yield (
                    [
                        (t[0], f'<span style="{REMOVED_STYLE}">{t[1]}</span>')
                        for t in slice_range(before, alo, ahi)
                    ]
                    + [
                        (t[0], f'<span style="{ADDED_STYLE}">{t[1]}</span>')
                        for t in slice_range(after, blo, bhi)
                    ]
                )
            else:
                yield (
                    (
                        [
                            (t[0], f"(changed) {t[1]}")
                            for t in slice_range(before, alo, ahi)
                        ]
                        + [
                            (t[0], f"(into) {t[1]}")
                            for t in slice_range(after, blo, bhi)
                        ]
                    )
                    if include_change_type_prefix
                    else (slice_range(before, alo, ahi) + slice_range(after, blo, bhi))
                )
        elif include_added and tag == "insert":
            if html_colour:
                yield [
                    (t[0], f'<span style="{ADDED_STYLE}">{t[1]}</span>')
                    for t in slice_range(after, blo, bhi)
                ]
            else:
                yield (
                    [(t[0], f"(added) {t[1]}") for t in slice_range(after, blo, bhi)]
                    if include_change_type_prefix
                    else slice_range(after, blo, bhi)
                )


def flatten_diff_html(nested: List[Union[tuple, List]], sep: str = "") -> str:
    """
    Recursively flatten a nested list of (indent, text) tuples into an HTML string.
    Each tuple is rendered as a <div> with a left margin corresponding to its indent level.
    No extra separator is inserted between lines.

    Parameters:
        nested (List[Union[tuple, List]]): The nested list structure.
        sep (str): Separator to use between lines (default is an empty string).

    Returns:
        str: The flattened HTML string.
    """
    output_lines = []

    def _flatten(item):
        if isinstance(item, list):
            for sub in item:
                _flatten(sub)
        else:
            indent, text = item
            output_lines.append(
                f'<div style="margin-left: {indent * 10}px; margin-bottom: 0;">{text}</div>'
            )

    _flatten(nested)
    return sep.join(output_lines)


def filter_unwanted(tuples: List[tuple]) -> List[tuple]:
    """
    Filter out unwanted (indent, text) tuples whose text contains specific substrings.

    Parameters:
        tuples (List[tuple]): List of (indent, text) tuples.

    Returns:
        List[tuple]: Filtered list.
    """
    unwanted = ("CDC_POST=", "CDC_PRE=", "WB$wombat", "CDC.ABTest", "CDC_AAref_Val")
    return [t for t in tuples if not any(s in t[1] for s in unwanted)]


def produce_visible_diff(before_html: str, after_html: str) -> str:
    """
    Produce an HTML diff for the visible text extracted from two HTML documents.

    Process:
      - Extract visible text as (indent, text) tuples (merging inline elements).
      - Normalize the indent levels.
      - Filter out any unwanted lines.
      - Compute the diff using tuple_diff.
      - Flatten the resulting diff groups into a single HTML string.

    Parameters:
        before_html (str): HTML content of the archived page.
        after_html (str): HTML content of the live page.

    Returns:
        str: An HTML string representing the diff.
    """
    before_tuples = filter_unwanted(
        normalize_indents(extract_text_with_indent(before_html))
    )
    after_tuples = filter_unwanted(
        normalize_indents(extract_text_with_indent(after_html))
    )
    diff_groups = list(
        tuple_diff(
            before=before_tuples,
            after=after_tuples,
            include_equal=True,  # Only show common text once from the original page.
            include_removed=True,
            include_added=True,
            include_replaced=True,
            include_change_type_prefix=False,
            html_colour=True,
        )
    )
    return flatten_diff_html(diff_groups, sep="")


def generate_comparison(restored_url: str, current_url: str) -> str:
    """
    Generate an HTML comparison between an archived RestoredCDC page and a live CDC page.

    Process:
      - Validate that the provided URLs are from the allowed domains.
      - Fetch HTML content from both URLs.
      - Extract and flatten the visible text for hidden cells.
      - Produce a visible HTML diff of the extracted text.
      - Return an HTML table containing:
            • Hidden cells with the full extracted text.
            • A visible cell with the diff output.

    Parameters:
        restored_url (str): URL of the archived page (must be on restoredcdc.org).
        current_url (str): URL of the live page (must be on cdc.gov).

    Returns:
        str: An HTML table as a string.

    Raises:
        ValueError: If either URL does not pass validation.
    """
    if not validate_url(restored_url, ["restoredcdc.org"]):
        raise ValueError(f"Archived URL '{restored_url}' is not allowed. Must be on restoredcdc.org.")

    if not validate_url(current_url, ["cdc.gov"]):
        raise ValueError(f"Current URL ' {current_url}' is not allowed. Must be on cdc.gov.")

    archived_html = fetch_html(restored_url, ["restoredcdc.org"])
    current_html = fetch_html(current_url, ["cdc.gov"])

    # Prepare hidden cells with full extracted text.
    archived_text_html = flatten_diff_html(
        normalize_indents(extract_text_with_indent(archived_html)), sep=""
    )
    current_text_html = flatten_diff_html(
        normalize_indents(extract_text_with_indent(current_html)), sep=""
    )

    # Generate the visible diff output.
    diff_html = produce_visible_diff(archived_html, current_html)

    return f"""
<table>
  <tbody>
    <tr>
      <td id="a" style="display: none;">{archived_text_html}</td>
      <td id="b" style="display: none;">{current_text_html}</td>
      <td id="diff-col">
        <span id="result" class="highlightable-filter">{diff_html}</span>
      </td>
    </tr>
  </tbody>
</table>
"""


# If this module is run directly, perform a test comparison.
if __name__ == "__main__":
    test_archived = "https://restoredcdc.org/www.cdc.gov/healthy-youth/lgbtq-youth/health-disparities-among-lgbtq-youth.html"
    test_current = "https://www.cdc.gov/healthy-youth/lgbtq-youth/health-disparities-among-lgbtq-youth.html"
    try:
        comparison = generate_comparison(test_archived, test_current)
        print(comparison)
    except Exception as err:
        logger.error(f"Comparison failed: {err}")
