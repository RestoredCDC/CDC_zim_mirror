#!/usr/bin/env python3

import argparse
from typing import Optional

from bs4 import BeautifulSoup, Tag
import logging
import re
from urllib import parse
from urllib.parse import urlparse
import json  # For rendering JSON in template
from flask import Flask, Response, redirect, render_template, request, url_for
from markupsafe import Markup  # For safely rendering JSON/HTML in template
from waitress import serve

# Database and Content Serving
import plyvel

# Search Feature imports
from whoosh import sorting, scoring
from whoosh.index import open_dir
from whoosh.qparser import MultifieldParser, OrGroup

# --- Comparison Feature Import ---
# The core logic for fetching & diffing pages lives in this processor module now.
from src.compare_feature.compare_processor import get_comparison_data

# --- Constants to appease lord CodeQL ---
# These are used to identify the CDC logo and favicon in HTML content.
# They are used in regex patterns to replace these with local static assets.
LOGO_KEYWORDS = {'cdc-logo', 'logo-notext', 'logo2'}
ICON_KEYWORDS = {'favicon', 'apple-touch-icon', 'safari-pinned-tab'}

# --- Argument Parsing ---
# Standard setup for command-line args like host, port, db locations.
parser = argparse.ArgumentParser(description="RestoredCDC Archive Server")
parser.add_argument("--hostname", default="127.0.0.1", type=str, help="Server hostname")
parser.add_argument("--port", default=9090, type=int, help="Server port")
parser.add_argument(
    "--dbfolder", default="cdc_database", type=str, help="Path to base LevelDB folder"
)
parser.add_argument(
    "--patchdbfolder",
    default="../patch_leveldb/patch_db",
    type=str,
    help="Path to patched LevelDB folder",
)
args = parser.parse_args()

# --- Logging Setup ---
# Basic logging config. Production might need more sophisticated setup (file rotation, etc.)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
# Using Flask's app.logger within routes is generally preferred for request context.

# --- Database Setup ---
# Try opening the LevelDB instances needed for serving content. Exit if they fail.
try:
    base_db = plyvel.DB(str(args.dbfolder), create_if_missing=False)
    patched_db = plyvel.DB(str(args.patchdbfolder), create_if_missing=False)
    # Create prefixed views for content ('c-') and mime types ('m-')
    base_content_db = base_db.prefixed_db(b"c-")
    base_mimetype_db = base_db.prefixed_db(b"m-")
    patched_content_db = patched_db.prefixed_db(b"c-")
    patched_mimetype_db = patched_db.prefixed_db(b"m-")
    # TODO: Consider adding a check here to see if the DBs are empty or valid?
except Exception as e:
    # Log the specific error to console/startup logs, but exit cleanly.
    print(f"❌ Error opening LevelDB databases: {e}")
    print(
        f"Ensure DB paths are correct: --dbfolder='{args.dbfolder}' --patchdbfolder='{args.patchdbfolder}'"
    )
    exit(1)


# --- Flask App Initialization ---
app = Flask(__name__)
# Setting Flask's logger level. Access via `app.logger`.
app.logger.setLevel(logging.INFO)

# --- Configuration ---
# Basic server config from args
hostName = args.hostname
serverPort = args.port
# Whoosh search index location
INDEX_DIR = "search_index"
# Note: Comparison feature configurations (Playwright settings, blocklists, etc.)
# were moved into src/comparison/comparison_utils.py for better modularity.

# --- HTML Manipulation Regex/Constants ---
# These are primarily used by the `lookup` route for injecting banners,
# fixing links, replacing search forms, etc. in the archived HTML content.
# (Keeping existing constants and regexes as is)
body_tag_regex = re.compile(r"(<body\b[^>]*>)", re.IGNORECASE)
svg_pattern = re.compile(r"<svg[^>]*>.*?</svg>", re.DOTALL)
NEWS_DISCLAIMER_HTML = """<div class="news-disclaimer" style="background-color: #f8d7da; color: #721c24; padding: 10px; border: 1px solid #f5c6cb; margin-bottom: 10px; font-weight: bold;">RestoredCDC is an archival snapshot; therefore, news items and outbreak information are not current.</div>"""
NEWS_SEARCH_TERMS = {
    "flu",
    "marburg",
    "outbreak",
    "situation",
    "news",
    "measles",
    "covid",
    "rsv",
}
DISCLAIMER_HTML = """<div id="restoredCDC_banner"> <div id="text_block"> <p id="disclaimer_text"> <strong>Original site:</strong> <span style="color: #333;">$NAME</span> | <strong>RestoredCDC.org</strong> is an independent project, not affiliated with CDC or any federal entity. Visit <a href="http://www.cdc.gov">CDC.gov</a> for free official information. Due to archival on <strong>January 6, 2025</strong>, recent outbreak data is unavailable. Videos are not restored. Access <a href="https://data.restoredcdc.org">data.restoredcdc.org</a> for restored data. Use of this site implies acceptance of this disclaimer. </p> <a id="toggle_disclaimer" href="javascript:void(0);">[More]</a> </div> <div id="disclaimer_buttons"> <a href="https://aboutus.restoredcdc.org/mission" target="_blank">About Us</a> <a href="https://github.com/RestoredCDC/CDC_zim_mirror/issues" target="_blank">Report Bug</a> <a href="/compare?cdc_url=$CDC_URL&this_url=$THIS_URL" target="_blank">Compare Content</a> </div></div>"""
BANNER_SCRIPT = """<script> document.addEventListener("DOMContentLoaded", function() { var searchForms = document.querySelectorAll('form.cdc-header-search-form'); searchForms.forEach(function(form) { form.action = "/search"; }); var toggle = document.getElementById("toggle_disclaimer"); if (toggle) { toggle.addEventListener("click", function() { var disclaimer = document.getElementById("disclaimer_text"); var banner = document.getElementById("restoredCDC_banner"); if (disclaimer.style.maxHeight && disclaimer.style.maxHeight !== "1.2em") { /* --- Collapse Logic (Seems OK) --- */ disclaimer.style.maxHeight = "1.2em"; disclaimer.style.overflow = "hidden"; disclaimer.style.whiteSpace = "nowrap"; disclaimer.style.textOverflow = "ellipsis"; this.innerText = "[More]"; setTimeout(() => { banner.style.height = ""; /* Reset banner height */ }, 300); } else { /* --- Expand Logic (FIXED) --- */ var scrollHeight = disclaimer.scrollHeight; /* --- FIX Start --- */ /* Set banner height to auto *before* text expansion starts animating */ /* This allows the banner's height transition (if defined in CSS) to work */ banner.style.height = 'auto'; /* --- FIX End --- */ /* Start the text expansion transition */ disclaimer.style.maxHeight = scrollHeight + "px"; disclaimer.style.overflow = "visible"; disclaimer.style.whiteSpace = "normal"; this.innerText = "[Less]"; /* After the text transition, ensure maxHeight doesn't constrain it */ setTimeout(() => { disclaimer.style.maxHeight = "none"; }, 300); /* Match text transition duration */ } }); } }); </script>"""
try:
    # Load CSS overrides if file exists
    with open("static/style_overrides.css", "r", encoding="utf-8") as css_file:
        STYLE_OVERRIDE = css_file.read()
except FileNotFoundError:
    app.logger.warning(
        "static/style_overrides.css not found. Proceeding without overrides."
    )
    STYLE_OVERRIDE = ""
# Search form replacement patterns
desktop_search_pattern = re.compile(
    r'<form id="cdc-desktop-search-form".*?</form>', re.DOTALL
)
desktop_search_replace = """<form id="cdc-desktop-search-form" class="cdc-header-search-form" role="search" action="/search" method="get"> <input class="form-control" type="search" name="q" data-search-input aria-label="Search" placeholder="Search RestoredCDC"> <button type="submit" title="Search"><span class="cdc-fa-magnifying-glass"></span></button> <button type="button" title="Clear Search" onclick="this.form.q.value=''"><span class="cdc-icon-close"></span></button></form>"""
sticky_search_pattern = re.compile(
    r'<form id="sticky-cdc-desktop-search-form".*?</form>', re.DOTALL
)
sticky_search_replace = """<form id="sticky-cdc-desktop-search-form" class="cdc-header-search-form" role="search" action="/search" method="get"> <input class="form-control" type="search" name="q" data-search-input aria-label="Search" placeholder="Search RestoredCDC"> <button type="submit" title="Search"><span class="cdc-fa-magnifying-glass"></span></button> <button type="button" title="Clear Search" onclick="this.form.q.value=''"><span class="cdc-icon-close"></span></button></form>"""
mobile_search_pattern = re.compile(
    r'<form id="cdc-mobile-search-form".*?</form>', re.DOTALL
)
mobile_search_replace = """<form id="cdc-mobile-search-form" class="cdc-header-search-form" role="search" action="/search" method="get"> <input class="form-control" type="search" name="q" data-search-input aria-label="Search" placeholder="Search RestoredCDC"> <button type="submit" title="Search"><span class="cdc-fa-magnifying-glass"></span></button> <button type="button" title="Clear Search" onclick="this.form.q.value=''"><span class="cdc-icon-close"></span></button></form>"""
# --- End HTML Constants ---


# --- Helper Functions ---
# Note: Comparison helpers (fetch_and_process_url, normalize_whitespace) were moved
# to src/comparison/comparison_utils.py


def replace_logo(html: str, new_logo_url: str, new_favicon_url: str) -> str:
    """
    Replaces known CDC logo/favicon URLs in HTML with paths to local static assets,
    using an HTML parser for safety and robustness.
    """
    try:
        # Generate paths to our static images (needs request context)
        new_logo_path = url_for("static", filename=f"images/{new_logo_url}")
        new_favicon_path = url_for("static", filename=f"images/{new_favicon_url}")

        # Parse the HTML
        # Using 'html.parser' is built-in, 'lxml' is faster if available/installed
        soup = BeautifulSoup(html, 'html.parser')

        # Find potentially relevant tags (add others like <source> if necessary)
        tags_to_check = soup.find_all(['img', 'link'])

        for tag in tags_to_check:
            if isinstance(tag, Tag):
                # Check 'src' attribute (primarily for <img>)
                original_src = tag.get('src')
                if original_src:
                    # Check if any logo keyword is in the src
                    if any(keyword in original_src for keyword in LOGO_KEYWORDS):
                        tag['src'] = new_logo_path
                        # Use app.logger if available, otherwise standard logging or print
                        try:
                            app.logger.debug(f"Replaced src='{original_src}' with '{new_logo_path}'")
                        except NameError: # If app.logger not directly accessible here
                            logging.debug(f"Replaced src='{original_src}' with '{new_logo_path}'")


                # Check 'href' attribute (primarily for <link>)
                original_href = tag.get('href')
                if original_href:
                    # Check for logo keywords first
                    if any(keyword in original_href for keyword in LOGO_KEYWORDS):
                        tag['href'] = new_logo_path
                        try:
                            app.logger.debug(f"Replaced href='{original_href}' with '{new_logo_path}'")
                        except NameError:
                            logging.debug(f"Replaced href='{original_href}' with '{new_logo_path}'")
                    # Else, check for icon keywords (avoid overwriting logo replacement)
                    elif any(keyword in original_href for keyword in ICON_KEYWORDS):
                        tag['href'] = new_favicon_path
                        try:
                            app.logger.debug(f"Replaced href='{original_href}' with '{new_favicon_path}'")
                        except NameError:
                             logging.debug(f"Replaced href='{original_href}' with '{new_favicon_path}'")
        else:
            # Log if a non-Tag element was somehow found (unlikely here)
            try:
                app.logger.warning(f"Skipping unexpected element type found by find_all: {type(tag)}")
            except NameError:
                logging.warning(f"Skipping unexpected element type found by find_all: {type(tag)}")

        # Return the modified HTML as a string
        return str(soup)

    except RuntimeError:
        # url_for needs an active request context. Log if called without one.
        # Use app.logger if available, otherwise standard logging or print
        try:
            app.logger.warning(
                "Could not generate static URLs for logo replacement outside request context."
            )
        except NameError:
             logging.warning(
                "Could not generate static URLs for logo replacement outside request context."
             )
        return html # Return original HTML if context fails
    except Exception as e:
        # Catch potential parsing errors or other issues
        # Use app.logger if available, otherwise standard logging or print
        try:
            app.logger.error(f"Error during HTML parsing/modification in replace_logo: {e}", exc_info=True)
        except NameError:
            logging.error(f"Error during HTML parsing/modification in replace_logo: {e}", exc_info=True)
        return html # Return original HTML on error


# Whoosh Search Helpers (Keep as is)
def process_snippets(snippet: str) -> str:
    """Cleans up Whoosh highlight snippets for better display."""
    # ... (keep existing implementation) ...
    snips = snippet.replace("\n", "").split("...")
    seen = set()
    unique_snips = []
    for fragment in snips:
        processed_snip = fragment.strip()
        if not processed_snip:
            continue
        lower_snip = processed_snip.lower()
        if lower_snip in seen:
            continue
        seen.add(lower_snip)
        if processed_snip[0].islower() and not processed_snip.startswith("..."):
            processed_snip = "..." + processed_snip
        if not processed_snip.endswith("..."):
            processed_snip += "..."
        unique_snips.append(processed_snip)
    return "\n".join(unique_snips)


def suggest_spelling(ix, query: str, fieldname: str = "content") -> Optional[str]:
    """Uses Whoosh's suggester to provide 'Did you mean?' functionality."""
    # ... (keep existing implementation) ...
    # Consider making fieldname a list ['title', 'content'] if using MultifieldParser here too
    with ix.searcher(weighting=scoring.BM25F()) as searcher:
        # Ensure parser used here matches the one in search_route if checking specific field
        parser = MultifieldParser(
            ["title", "content"], schema=ix.schema
        )  # Match search_route parser
        try:
            original_q = parser.parse(query)
            corrected = searcher.correct_query(original_q, query)
            if corrected.query != original_q:
                return corrected.string
        except Exception as e:
            app.logger.warning(f"Could not get spelling suggestions for '{query}': {e}")
    return None


# --- End Helper Functions ---


# --- Flask Routes ---
@app.route("/")
def home():
    """Redirects website root ('/') to the expected archive root path."""
    # We assume the archive starts under /www.cdc.gov/ based on original setup
    return redirect("/www.cdc.gov/")


@app.route("/<path:subpath>")
def lookup(subpath: str):
    """
    Main route for serving archived content.
    Looks up the path in LevelDB, handles redirects stored in DB,
    and performs HTML modifications (banner injection, link fixing, etc.)
    before returning the content.
    """
    # ... (Keep existing implementation - it's complex but separate from compare logic) ...
    # This route is responsible for generating the correct 'Compare Content' link
    # by replacing $THIS_URL and $CDC_URL in the DISCLAIMER_HTML.
    try:
        full_path = parse.unquote(subpath)
        content = patched_content_db.get(bytes(full_path, "UTF-8"))
        if content is None:
            content = base_content_db.get(bytes(full_path, "UTF-8"))
        mimetype_bytes = patched_mimetype_db.get(bytes(full_path, "UTF-8"))
        if mimetype_bytes is None:
            mimetype_bytes = base_mimetype_db.get(bytes(full_path, "UTF-8"))

        if content is None or mimetype_bytes is None:
            app.logger.warning(f"404 Not Found: {full_path}")
            return render_template("404.html"), 404

        mimetype = mimetype_bytes.decode("utf-8")
        if mimetype == "=redirect=":
            redirect_target = content.decode("utf-8")
            app.logger.info(f"Redirecting {full_path} to /{redirect_target}")
            return redirect(f"/{redirect_target}")

        if mimetype.startswith("text/html"):
            content_str = content.decode("utf-8")
            content_str = content_str.replace(
                "</head>", f"<style>{STYLE_OVERRIDE}</style>{BANNER_SCRIPT}</head>"
            )
            this_host = request.host_url.strip("/")
            this_full_url = f"{this_host}/{full_path}"
            cdc_base_url = "https://www.cdc.gov"
            cdc_path = (
                full_path.replace("www.cdc.gov/", "", 1)
                if full_path.startswith("www.cdc.gov/")
                else full_path
            )
            cdc_full_url = f"{cdc_base_url}/{cdc_path}"
            current_disclaimer = (
                DISCLAIMER_HTML.replace("$NAME", full_path)
                .replace("$THIS_URL", this_full_url)
                .replace("$CDC_URL", cdc_full_url)
            )
            content_str = body_tag_regex.sub(
                r"\1" + current_disclaimer, content_str, count=1
            )
            content_str = content_str.replace(
                "An official website of the United States government", ""
            )
            content_str = replace_logo(content_str, "logo.png", "favicon.ico")
            content_str = re.sub(svg_pattern, "", content_str)
            content_str = content_str.replace("us_flag_small", "")
            content_str = content_str.replace(
                "Centers for Disease Control and Prevention. CDC twenty four seven. Saving Lives, Protecting People",
                "",
            )
            content_str = content_str.replace(
                'alt="Centers for Disease Control and Prevention"', ""
            )
            content_str = content_str.replace('alt="U.S. flag"', "")
            content_str = content_str.replace("hp2024.js", "")
            content_str = content_str.replace(
                'id="cdc-footer-nav"',
                'id="cdc-footer-nav" style="display:block !important;"',
            )
            content_str = content_str.replace("<title>", "<title>Restored CDC | ")
            content_str = content_str.replace(
                'href="https://www.cdc.gov', f'href="{this_host}'
            )
            content_str = content_str.replace(
                'href="//www.cdc.gov', f'href="{this_host}'
            )
            content_str = re.sub(
                desktop_search_pattern, desktop_search_replace, content_str
            )
            content_str = re.sub(
                sticky_search_pattern, sticky_search_replace, content_str
            )
            content_str = re.sub(
                mobile_search_pattern, mobile_search_replace, content_str
            )
            if (
                any(term in full_path.lower() for term in NEWS_SEARCH_TERMS)
                or full_path.endswith("/index.html")
                or full_path == "/www.cdc.gov/"
            ):
                content_str = re.sub(
                    r"(News</h2>)", r"\1" + NEWS_DISCLAIMER_HTML, content_str, count=1
                )
                if NEWS_DISCLAIMER_HTML not in content_str:
                    content_str = re.sub(
                        r"(aria-label=\"Main Content Area\">)",
                        r"\1" + NEWS_DISCLAIMER_HTML,
                        content_str,
                        count=1,
                    )
            return Response(content_str, mimetype=mimetype)
        else:
            return Response(content, mimetype=mimetype)
    except Exception as e:
        # Log detailed error, return generic 404
        app.logger.error(f"Error processing lookup for {subpath}: {e}", exc_info=True)
        return render_template("404.html"), 404


# --- Comparison Route (Refactored) ---
@app.route("/compare", methods=["GET"])
def compare():
    """
    Handles requests to compare an archived page with its live counterpart.

    Retrieves URLs from query parameters, calls the comparison processor module
    to handle fetching and diffing, and renders the results template.
    Includes SSRF protection via URL validation within the processor.
    """
    # Get URLs from query params (e.g., /compare?this_url=...&cdc_url=...)
    this_url_arg = request.args.get("this_url", "").strip()  # Archived page URL
    cdc_url_arg = request.args.get("cdc_url", "").strip()  # Live page URL
    route_logger = app.logger  # Use Flask's logger for this request

    # Basic check: need both URLs
    if not this_url_arg or not cdc_url_arg:
        route_logger.warning("Comparison request missing one or both URLs.")
        return "Error: Both 'this_url' and 'cdc_url' parameters are required.", 400

    # Add default scheme if missing (basic hygiene, real validation happens in processor)
    if not (this_url_arg.startswith("http://") or this_url_arg.startswith("https://")):
        this_url_arg = "https://" + this_url_arg
        route_logger.debug(f"Added scheme to this_url: {this_url_arg}")
    if not (cdc_url_arg.startswith("http://") or cdc_url_arg.startswith("https://")):
        cdc_url_arg = "https://" + cdc_url_arg
        route_logger.debug(f"Added scheme to cdc_url: {cdc_url_arg}")

    # Determine the expected host for the *archived* URL based on how this server was accessed.
    # This is used for SSRF protection inside get_comparison_data.
    expected_host = request.host  # Includes host & port if non-standard

    # Delegate the core work (fetching, diffing, error handling) to the processor module.
    route_logger.info(
        f"Calling comparison processor for: {this_url_arg} and {cdc_url_arg}"
    )
    try:
        # Pass URLs, expected host for validation, and logger
        comparison_data = get_comparison_data(
            this_url_arg, cdc_url_arg, expected_host, route_logger
        )
        route_logger.info(
            f"Comparison processing complete. Error flag: {comparison_data.get('is_error')}"
        )
    except Exception as e:
        # Catch totally unexpected errors *during the call* to the processor
        route_logger.error(
            f"Unexpected error calling get_comparison_data: {e}", exc_info=True
        )
        # Prepare a default error dictionary to send to the template
        comparison_data = {
            "lines_orig_A": [],
            "lines_orig_B": [],
            "render_instructions": [],
            "is_error": True,
            "error_msg1": "Error: Comparison failed due to an internal server error. Please check logs.",
            "error_msg2": "Error: Comparison failed due to an internal server error. Please check logs.",
        }

    # Prepare the disclaimer banner (remove the 'Compare' link itself)
    path_display = (
        urlparse(this_url_arg).path.lstrip("/") or "homepage"
    )  # For display in banner
    final_disclaimer = DISCLAIMER_HTML.replace("$NAME", path_display)
    final_disclaimer = re.sub(
        r'<a href="/compare.*?</a>', "", final_disclaimer
    )  # Remove link

    # Prepare the list of URLs for the template context
    pageURLs = [cdc_url_arg, this_url_arg]  # Order: [Live, Archived]

    # Render the template, passing data needed for client-side JS rendering
    return render_template(
        "compare.html",
        # Comparison data (JSON-encoded and marked safe for embedding in <script>)
        lines_orig_A_json=Markup(json.dumps(comparison_data.get("lines_orig_A", []))),
        lines_orig_B_json=Markup(json.dumps(comparison_data.get("lines_orig_B", []))),
        render_instructions_json=Markup(
            json.dumps(comparison_data.get("render_instructions", []))
        ),
        # Error status and messages
        is_error=comparison_data.get(
            "is_error", True
        ),  # Default to True if key missing
        error_msg1=comparison_data.get("error_msg1"),
        error_msg2=comparison_data.get("error_msg2"),
        # Other template context
        comparison_timestamp_utc=comparison_data.get("comparison_timestamp_utc"),
        disclaimer=Markup(final_disclaimer),
        pageURLs=pageURLs,
        banner_script=Markup(BANNER_SCRIPT),
    )


# --- Search Routes (Keep as is) ---
@app.route("/search")
def search_route():
    """Handles search queries using Whoosh index."""
    # ... (keep existing implementation) ...
    user_query = request.args.get("q", "").strip()
    MAX_QUERY_LENGTH = 200
    if len(user_query) > MAX_QUERY_LENGTH:
        trimmed_query = user_query[:MAX_QUERY_LENGTH]
        notice = f"Query shortened to {MAX_QUERY_LENGTH} chars."
    else:
        trimmed_query = user_query
        notice = None
    page_str = request.args.get("page", "1")
    sortby = request.args.get("sortby", "score")
    try:
        page_num = max(1, int(page_str))
    except ValueError:
        page_num = 1
    results_list = []
    total_hits = 0
    did_you_mean = None
    if trimmed_query:
        try:
            ix = open_dir(INDEX_DIR)
            with ix.searcher(weighting=scoring.BM25F()) as searcher:
                parser = MultifieldParser(
                    ["title", "content"], schema=ix.schema, group=OrGroup.factory(0.8)
                )
                try:
                    qobj = parser.parse(trimmed_query)
                except Exception as e:
                    app.logger.error(f"Error parsing query '{trimmed_query}': {e}")
                    return "Error processing query.", 500
                facet = None
                if sortby == "title":
                    facet = sorting.FieldFacet("title", reverse=False)
                page_len = 15
                try:
                    page_obj = searcher.search_page(
                        qobj, page_num, pagelen=page_len, sortedby=facet, terms=True
                    )
                except Exception as e:
                    app.logger.error(f"Search execution error: {e}", exc_info=True)
                    return "Search error.", 500
                if page_num == 1 and len(page_obj) == 0:
                    did_you_mean = suggest_spelling(ix, trimmed_query)
                if page_obj.results:
                    page_obj.results.fragmenter.maxchars = 250
                    page_obj.results.fragmenter.surround = 40
                total_hits = page_obj.total
                for hit in page_obj:
                    snippet = hit.highlights("content", top=3)
                    cleaned_snippet = process_snippets(snippet)
                    results_list.append(
                        {
                            "title": hit.get("title", "No Title Provided"),
                            "path": hit["path"],
                            "snippet": cleaned_snippet,
                        }
                    )
        except Exception as e:
            app.logger.error(f"Search index error: {e}", exc_info=True)
            return "Search unavailable.", 503
    final_disclaimer = DISCLAIMER_HTML.replace("$NAME", "Search Results")
    final_disclaimer = re.sub(r'<a href="/compare.*?</a>', "", final_disclaimer)
    return render_template(
        "search_results.html",
        query=trimmed_query,
        results=results_list,
        total=total_hits,
        page=page_num,
        did_you_mean=did_you_mean,
        sortby=sortby,
        disclaimer=Markup(final_disclaimer),
        notice=notice,
    )


@app.route("/search.cdc.gov/search/")
def cdc_search_redirect():
    """Catches legacy CDC search URLs and redirects them safely to local search."""
    # Try to get 'q' first (used by replaced forms if they somehow hit this route,
    # and potentially by original desktop/sticky forms).
    # Fall back to 'query' (used by the original mobile form and maybe others).
    user_query = request.args.get("q")
    if user_query is None:  # If 'q' is not present, try 'query'
        user_query = request.args.get("query", "")  # Default to empty if neither exists
    sanitized_q = user_query.replace("\\", "")  # Basic sanitization
    parsed = urlparse(sanitized_q)
    # Prevent open redirect by checking for scheme/host in the query param
    if parsed.scheme or parsed.netloc:
        app.logger.warning(
            f"Blocked potential open redirect attempt via legacy search URL: {user_query}"
        )
        return redirect(
            url_for("search_route", q="")
        )  # Redirect to local search safely
    # Redirect to local search using 'q' param expected by our search_route
    return redirect(url_for("search_route", q=sanitized_q))


# --- End Search Routes ---


# --- Main Execution ---
if __name__ == "__main__":
    # Entry point when script is run directly
    app.logger.info(
        f"Starting RestoredCDC server via Waitress on http://{hostName}:{serverPort}"
    )
    # Use Waitress, a production-quality WSGI server
    serve(app, host=hostName, port=serverPort, threads=8)  # `threads` can be adjusted
