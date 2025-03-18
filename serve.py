from urllib import parse
from urllib.parse import urlparse
from flask import Flask, Response, redirect, render_template, request, url_for, jsonify
from waitress import serve
import argparse
import plyvel
import re
import json
from src.compare_html.compare import generate_comparison

# Whoosh-reloaded imports for search functionality
from whoosh.index import open_dir
from whoosh.qparser import QueryParser, OrGroup, MultifieldParser
from whoosh import sorting, scoring

parser = argparse.ArgumentParser()
parser.add_argument('--hostname', default="127.0.0.1", type=str)
parser.add_argument('--port', default=9090, type=int)
parser.add_argument('--dbfolder', default="cdc_database", type=str)
args = parser.parse_args()

# this is the path of the LevelDB database we converted from .zim using zim_converter.py
db = plyvel.DB(str(args.dbfolder))

# the LevelDB database has 2 keyspaces, one for the content, and one for its type
# please check zim_converter.py script comments for more info
content_db = db.prefixed_db(b"c-")
mimetype_db = db.prefixed_db(b"m-")

app = Flask(__name__)

# serving to localhost interfaces at port 9090
hostName = args.hostname
serverPort = args.port
# Where the whoosh search index lives
INDEX_DIR = "search_index"

# we will use the following regex to add a disclaimer after the body tag
body_tag_regex = re.compile(r"(<body\b[^>]*>)", re.IGNORECASE)
body_end_tag_regex = re.compile(r"</body>", re.IGNORECASE)
# CDC logo replace
# logo_pattern = r"cdc-logo|logo-notext|logo2|favicon|apple-touch-icon|safari-pinnned-tab|us_flag_small"
svg_pattern = re.compile(r"<svg[^>]*>.*?</svg>", re.DOTALL)

def replace_logo(html, new_logo_url, new_favicon_url):
    """
    Replace the CDC logo/favicons with the RestoredCDC versions.
    """

    # Patterns to match <img> and <link> sources for CDC logos and favicons
    logo_pattern = r'(href|src)=(["\'])([^"\']*?(?:cdc-logo|logo-notext|logo2)[^"\']*)(["\'])'
    icon_pattern = r'(["\'])([^"\']*?(?:favicon|apple-touch-icon|safari-pinned-tab)[^"\']*)(["\'])'

    # Generate URLs using Flask's `url_for()`
    new_logo_path = url_for('static', filename=f'images/{new_logo_url}')
    new_favicon_path = url_for('static', filename=f'images/{new_favicon_url}')

    # Replace matched patterns with new URLs
    html = re.sub(logo_pattern, rf'\1=\2{new_logo_path}\4', html)
    html = re.sub(icon_pattern, rf'\1{new_favicon_path}\3', html)

    return html


# Fix floating navigation
nav_pattern = r'(<nav\b[^>]*\bclass="[^"]*\bnavbar navbar-expand-lg fixed-top navbar-on-scroll hide\b[^"]*"[^>]*)>'
nav_replace = r'\1 style = "top: 55px;">'

#News disclaimer search and injection
# Regular expression to match the start of the News section
NEWS_SECTION_PATTERN = re.compile(
    r'(<section class="news[^>]*>\s*<h2>.*?</h2>\s*)',
    re.DOTALL
)

NEWS_DISCLAIMER_HTML = """
<div class="news-disclaimer" style="background-color: #f8d7da; color: #721c24; padding: 10px; border: 1px solid #f5c6cb; margin-bottom: 10px; font-weight: bold;">
    RestoredCDC is an archival snapshot; therefore, news items and outbreak information are not current.
</div>
"""

NEWS_SEARCH_TERMS = {"flu", "marburg","outbreak","situation","news","measles","covid","rsv"}

# this disclaimer will be at the top of every page.
DISCLAIMER_HTML = """
<div id="restoredCDC_banner">
  <div id="text_block">
    <p id="disclaimer_text">
      <strong>Original site:</strong> <span style="color: #333;">$NAME</span> |
      <strong>RestoredCDC.org</strong> is an independent project, not affiliated with CDC or any federal entity. Visit <a href="http://www.cdc.gov">CDC.gov</a> for free official information. Due to archival on <strong>January 6, 2025</strong>, recent outbreak data is unavailable. Videos are not restored. Access <a href="https://data.restoredcdc.org">data.restoredcdc.org</a> for restored data. Use of this site implies acceptance of this disclaimer.
    </p>
    <a id="toggle_disclaimer" href="javascript:void(0);">[More]</a>
  </div>
  <div id="disclaimer_buttons">
    <a href="https://aboutus.restoredcdc.org/mission" target="_blank">About Us</a>
    <a href="https://github.com/RestoredCDC/CDC_zim_mirror/issues" target="_blank">Report Bug</a>
    <a href="/compare?cdc_url=$CDC_URL&this_url=$THIS_URL" target="_blank">Compare Content</a>
  </div>
</div>
"""

BANNER_SCRIPT = """
<script>
document.addEventListener("DOMContentLoaded", function() {
    var searchForms = document.querySelectorAll('form.cdc-header-search-form');
    searchForms.forEach(function(form) {
        form.action = "/search";
    });

    document.getElementById("toggle_disclaimer").addEventListener("click", function() {
        var disclaimer = document.getElementById("disclaimer_text");
        var banner = document.getElementById("restoredCDC_banner");

        if (disclaimer.style.maxHeight && disclaimer.style.maxHeight !== "1.2em") {
            // Collapse disclaimer
            disclaimer.style.maxHeight = "1.2em";
            disclaimer.style.overflow = "hidden";
            disclaimer.style.whiteSpace = "nowrap";
            disclaimer.style.textOverflow = "ellipsis";
            this.innerText = "[More]";

            // Shrink banner after transition
            setTimeout(() => {
                banner.style.height = ""; // Reset to auto height
            }, 300); // Match transition duration
        } else {
            // Expand disclaimer
            disclaimer.style.maxHeight = disclaimer.scrollHeight + "px";
            disclaimer.style.overflow = "visible";
            disclaimer.style.whiteSpace = "normal";
            this.innerText = "[Less]";

            // Expand banner dynamically
            banner.style.height = (banner.scrollHeight + disclaimer.scrollHeight) + "px";

            // Reset maxHeight after transition completes
            setTimeout(() => {
                disclaimer.style.maxHeight = "none"; // Allow natural height expansion
            }, 300);
        }
    });
});
</script>

"""
# Read the CSS file
with open("static/style_overrides.css", "r", encoding="utf-8") as css_file:
    STYLE_OVERRIDE = css_file.read()

# Patterns to replace the disabled search forms in the legacy code with functional ones
desktop_search_pattern = re.compile(
    r'<form id="cdc-desktop-search-form".*?</form>', re.DOTALL
)
desktop_search_replace = """
<form id="cdc-desktop-search-form" class="cdc-header-search-form" role="search" action="/search" method="get">
    <input class="form-control" type="search" name="q" data-search-input aria-label="Search" placeholder="Search RestoredCDC">
    <button type="submit" title="Search"><span class="cdc-fa-magnifying-glass"></span></button>
    <button type="button" title="Clear Search" onclick="document.querySelector('#cdc-desktop-search-form input[name=q]').value=''">
        <span class="cdc-icon-close"></span>
    </button>
</form>
"""

sticky_search_pattern = re.compile(
    r'<form id="sticky-cdc-desktop-search-form".*?</form>', re.DOTALL
)
sticky_search_replace = """
<form id="sticky-cdc-desktop-search-form" class="cdc-header-search-form" role="search" action="/search" method="get">
    <input class="form-control" type="search" name="q" data-search-input aria-label="Search" placeholder="Search RestoredCDC">
    <button type="submit" title="Search"><span class="cdc-fa-magnifying-glass"></span></button>
    <button type="button" title="Clear Search" onclick="document.querySelector('#sticky-cdc-desktop-search-form input[name=q]').value=''">
        <span class="cdc-icon-close"></span>
    </button>
</form>
"""

search_toggle_pattern = re.compile(
        r'<form action="https://search.cdc.gov/search/".*?</form>',re.DOTALL
)
search_toggle_replace = """
<form action="/search" method="GET" class="cdc-header-search-form" role="search">
	<a href="#" id="cdc-search__toggle">Search</a>
	<div class="input-group cdc-header__search__group">
		<span class="cdc-header__search-icon cdc-fa-magnifying-glass" aria-hidden="true"></span>
		<input class="form-control" data-search-input="" autocomplete="off" type="search" name="query" id="cdc-search__input" maxlength="300" placeholder="" autocorrect="on" spellcheck="false"><div class="cdc-search-complete"></div>
		<button class="cdc-header__search-submit btn" type="submit" id="cdc-search__submit">Search RestoredCDC</button>
	</div>
</form>
"""


mobile_search_pattern = re.compile(
    r'<form id="cdc-mobile-search-form".*?</form>', re.DOTALL
)
mobile_search_replace = """
<form id="cdc-mobile-search-form" class="cdc-header-search-form" role="search" action="/search" method="get">
    <input class="form-control" type="search" name="q" data-search-input aria-label="Search" placeholder="Search RestoredCDC">
    <button type="submit" title="Search"><span class="cdc-fa-magnifying-glass"></span></button>
    <button type="button" title="Clear Search" onclick="document.querySelector('#cdc-mobile-search-form input[name=q]').value=''">
        <span class="cdc-icon-close"></span>
    </button>
</form>
"""

@app.route("/")
def home():
    """
    we need the root of the site to be /www.cdc.gov/ so if our domain is
    www.example.com when someone visits www.example.com we need to redirect
    them to www.example.com/www.cdc.com/ subfolder. the home route ensures that.
    """
    return redirect("/www.cdc.gov/")



@app.route("/<path:subpath>")
def lookup(subpath):
    """
    Catch-all route
    from here we will collect the path requested after www.example.com
    and look for it in the database so if a request for www.example.com/www.cdc.gov/something/image.jpg
    is requested, here we capture /www.cdc.gov/something/image.jpg part of it, remove the first / character
    then search for the remaining path in database, get its data and type from the database
    and serve it back directly.
    """

    try:
        # capture the path and fix its quoted characters
        full_path = parse.unquote(subpath)
        # print(f"Request for: {full_path}")

        # convert the path to bytes and get the content from the database
        content = content_db.get(bytes(full_path, "UTF-8"))
        # convert the path to bytes and get the content type from the database and decode it to a string
        # (mimetype is always a string)
        mimetype = mimetype_db.get(bytes(full_path, "UTF-8")).decode("utf-8")

        # if the content type is the special value "=redirect=" this path redirected to another
        # at crawl time. for relative paths to work, we need to just redirect the user to that
        # target path.
        if mimetype == "=redirect=":
            return redirect(f'/{content.decode("utf-8")}')

        if mimetype.startswith("text/html"):
            content = content.decode("utf-8")
            content = content.replace("</head>", 
                                      "<style>" + STYLE_OVERRIDE + "</style>" + 
                                      BANNER_SCRIPT +  
                                      "</head>")
            # here we add the disclaimer with a regex if the request is for a html file.
            content = body_tag_regex.sub(r"\1" + DISCLAIMER_HTML, content, count=1)
            # and replace the official notice
            content = content.replace(
                "An official website of the United States government", ""
            )
            content = re.sub(re.escape("$NAME"), subpath, content, count=1)
            content = replace_logo(content,'logo.png','favicon.ico')
            content = re.sub(svg_pattern, "", content)
            content = content.replace("$CDC_URL","https://" + subpath)
            content = content.replace("$THIS_URL","https://www.restoredcdc.org/"+subpath)

            content = content.replace("us_flag_small","")
            content = content.replace(
                "Centers for Disease Control and Prevention. CDC twenty four seven. Saving Lives, Protecting People",
                "",
            )
            content = content.replace(
                'alt="Centers for Disease Control and Prevention"', ""
            )
            content = content.replace('alt="U.S. flag"', "")
            content = content.replace("hp2024.js", "")
            content = content.replace(
                'id="cdc-footer-nav"',
                'id="cdc-footer-nav" style="display:block !important;"',
            )
            #content = re.sub(nav_pattern, nav_replace, content, count=1)
            content = content.replace("<title>", "<title>Restored CDC | ")
            content = content.replace(
                'href="https://www.cdc.gov', 'href="https://www.restoredcdc.org'
            )
            content = re.sub(
                desktop_search_pattern,
                desktop_search_replace,
                content,
            )
            content = re.sub(
                sticky_search_pattern,
                sticky_search_replace,
                content,
            )
            content = re.sub(
                mobile_search_pattern,
                mobile_search_replace,
                content,
            )

            #content = re.sub(
            #    search_toggle_pattern,
            #    search_toggle_replace,
            #    content,
            #)
            content = re.sub(r"(News</h2>)", r"\1" + NEWS_DISCLAIMER_HTML, content, count=1)

            # Apply News disclaimer **only** when the request is for index.html
            if request.path.endswith("/index.html") or request.path == "/www.cdc.gov/":
                content = NEWS_SECTION_PATTERN.sub(r"\1" + NEWS_DISCLAIMER_HTML, content)

            if any(term in request.path.lower() for term in NEWS_SEARCH_TERMS):
                content = re.sub(r"(aria-label=\"Main Content Area\">)", r"\1" + NEWS_DISCLAIMER_HTML, content, count=1)
        #  content = re.sub(body_end_tag_regex, search_override + "\n</body>", content)
        # if the path was not a redirect, serve the content directly along with its mimetype
        # the browser will know what to do with it.
        return Response(content, mimetype=mimetype)
    except Exception as e:
        # if anything is wrong, just send a 404
        # print(f"Error retrieving {full_path}: {e}")
        # return Response("404 Not Found", status=404, mimetype="text/plain")
        # return render_template("404.html", error=str(e)), 404
        return render_template("404.html"), 404


@app.route('/compare', methods=['GET'])
def compare():
    cdc_url = request.args.get("cdc_url", "").strip()
    this_url = request.args.get("this_url", "").strip()

    if not cdc_url or not this_url:
        return "Error: Both URLs are required.", 400

    # Generate the JSON comparison data
    comparison_report = generate_comparison(this_url, cdc_url)
    final_disclaimer = DISCLAIMER_HTML.replace(
        "/compare?this_url=https://restoredcdc.org/$NAME&cdc_url=https://www.cdc.gov/$NAME_NO_PREFIX",
        "",
    )
    final_disclaimer = final_disclaimer.replace("Compare with cdc.gov", "")
    final_disclaimer = final_disclaimer.replace("$NAME", "www.cdc.gov/")

    URLs = [cdc_url, this_url]

    return render_template("compare.html", comparison_report=comparison_report, disclaimer=final_disclaimer,
                           pageURLs = URLs)


def process_snippets(snippet):
    """
    Removes duplicated snippet fragments from a Whoosh highlight string,
    ensures each snippet ends with '...', and adds '...' if it starts mid-sentence.
    """
    snips = snippet.replace("\n", "").split("...")
    seen = set()
    unique_snips = []
    for fragment in snips:
        processed_snip = fragment.strip()
        if not processed_snip:
            continue
        lower_snip = processed_snip.lower()
        if lower_snip in seen:
            # Skip any exact duplicates (case-insensitive).
            continue
        seen.add(lower_snip)
        # If snippet starts in the middle of a sentence, prepend '...'.
        if processed_snip[0].islower() and not processed_snip.startswith("..."):
            processed_snip = "..." + processed_snip
        # Ensure snippet ends with '...'.
        if not processed_snip.endswith("..."):
            processed_snip += "..."
        unique_snips.append(processed_snip)
    return "\n".join(unique_snips)


def suggest_spelling(ix, query, fieldname="content"):
    """
    Suggests a corrected query if Whoosh finds a likely alternative
    (e.g., user gets 0 results for a misspelled term).
    """
    with ix.searcher(weighting=scoring.BM25F()) as searcher:
        # parser = QueryParser(fieldname, ix.schema, group=OrGroup.factory(0.8))
        parser = MultifieldParser(["title", "content"], schema=ix.schema)
        original_q = parser.parse(query)
        corrected = searcher.correct_query(original_q, query)
        if corrected.query != original_q:
            return corrected.string
    return None


@app.route("/search")
def search_route():
    """
    Primary search endpoint. Uses Whoosh-reloaded to parse the user query,
    apply optional sorting, truncate overly long queries,
    and return relevant results or 'did you mean' suggestions.
    """
    user_query = request.args.get("q", "").strip() if "q" in request.args else ""

    # Limit queries to prevent performance issues or crashes on extremely long inputs.
    MAX_QUERY_LENGTH = 200
    if len(user_query) > MAX_QUERY_LENGTH:
        trimmed_query = user_query[:MAX_QUERY_LENGTH]
        notice = f"Your search query was too long and has been shortened to {MAX_QUERY_LENGTH} characters."
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
        ix = open_dir(INDEX_DIR)
        with ix.searcher(weighting=scoring.BM25F()) as searcher:
            parser = QueryParser("content", ix.schema, group=OrGroup.factory(0.8))
            try:
                qobj = parser.parse(trimmed_query)
            except Exception as e:
                # app.logger.error(f"Error parsing query: {e}")  # If we setup logging later
                return "An error occurred while processing your request.", 500

            # Determine sorting if specified (either by score or by title).
            facet = None
            if sortby == "title":
                facet = sorting.FieldFacet("title", reverse=False)

            page_len = 15
            try:
                page_obj = searcher.search_page(
                    qobj, page_num, pagelen=page_len, sortedby=facet, terms=True
                )
            except Exception as e:
                # app.logger.error(f"Error retrieving page: {e}")  # If we setup logging later
                return "An internal error has occurred.", 500

            # Attempt "did you mean" if no hits on first page.
            if page_num == 1 and len(page_obj) == 0:
                did_you_mean = suggest_spelling(ix, trimmed_query)

            # Configure highlight snippet length.
            if page_obj.results:
                page_obj.results.fragmenter.maxchars = 250
                page_obj.results.fragmenter.surround = 40

            total_hits = page_obj.total

            for hit in page_obj:
                snippet = hit.highlights("content", top=3)
                cleaned_snippet = process_snippets(snippet)
                results_list.append(
                    {
                        "title": hit.get("title", "No Title"),
                        "path": hit["path"],
                        "snippet": cleaned_snippet,
                    }
                )

    # Insert disclaimer text after we finalize the query.
    final_disclaimer = DISCLAIMER_HTML.replace("$NAME", "www.cdc.gov/")

    return render_template(
        "search_results.html",
        query=trimmed_query,
        results=results_list,
        total=total_hits,
        page=page_num,
        did_you_mean=did_you_mean,
        sortby=sortby,
        disclaimer=final_disclaimer,
        notice=notice,
    )


@app.route("/search.cdc.gov/search/")
def cdc_search_redirect():
    """
    Catches legacy references to search.cdc.gov and redirects queries
    back to our local /search route, but prevents untrusted URL redirects.
    This is a bit hacky, but prevents needing to change the <path:subpath> route redirect.
    """
    user_query = request.args.get("q", "")

    # Replace backslashes with empty strings to guard against browser quirks
    sanitized_q = user_query.replace("\\", "")

    # Parse the sanitized query
    parsed = urlparse(sanitized_q)

    # If the user’s "q" has a scheme or netloc, that indicates an absolute URL
    # which we don't want to honor (could cause an open redirect).
    # So we either block or redirect them to a safe default:
    if parsed.scheme or parsed.netloc:
        # Option A: redirect to safe default
        return redirect("/search?q=")

        # Option B: return a 400 or some safe page
        # return "Invalid redirect URL.", 400

    # If it passed the checks, safe to incorporate into our local /search
    return redirect(f"/search?q={sanitized_q}")


if __name__ == "__main__":
    print(f"Starting cdcmirror server process at port {serverPort}")
    serve(app, host=hostName, port=serverPort)
