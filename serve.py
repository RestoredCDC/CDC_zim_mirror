from urllib import parse
from flask import Flask, Response, redirect, render_template
from waitress import serve
import plyvel
import re

# this is the path of the LevelDB database we converted from .zim using zim_converter.py
db = plyvel.DB('./cdc_database')

# the LevelDB database has 2 keyspaces, one for the content, and one for its type
# please check zim_converter.py script comments for more info
content_db = db.prefixed_db(b"c-")
mimetype_db = db.prefixed_db(b"m-")

app = Flask(__name__)

# serving to localhost interfaces at port 9090
hostName = "127.0.0.1"
serverPort = 9090

# we will use the following regex to add a disclaimer after the body tag 
body_tag_regex = re.compile(r'(<body\b[^>]*>)', re.IGNORECASE)
body_end_tag_regex = re.compile(r"</body>", re.IGNORECASE)
# CDC logo replace
logo_pattern = r"cdc-logo|logo-notext|logo2|favicon|apple-touch-icon|safari-pinnned-tab|us_flag_small"
svg_pattern = re.compile(r"<svg[^>]*>.*?</svg>", re.DOTALL)


# Fix floating navigation
nav_pattern = r'(<nav\b[^>]*\bclass="[^"]*\bnavbar navbar-expand-lg fixed-top navbar-on-scroll hide\b[^"]*"[^>]*)>'
nav_replace = r'\1 style = "top: 100px;">'

# this disclaimer will be at the top of every page.
DISCLAIMER_HTML = '''
<div style="position: sticky; top: 0; background: #f8f9fa; height: 100px; padding: 5px; border-bottom: 2px solid #ddd; z-index: 1000; display: flex; align-items:center;justify-content: space-between; font-size: 0.9em; overflow:hidden;">
  <div style="flex: 1; overflow-y: auto; padding-right: 5px; max-height:100px;">
    <p style = "margin: 0; font-size: color: #555;">Original site: $NAME<br> RestoredCDC.org is an independent project and is not affiliated with, endorsed by, or associated with the Centers for Disease Control and Prevention (CDC) or any government entity. The CDC provides information free of charge at <a href="http://www.cdc.gov">CDC.gov</a>. Note the following: 1) Due to archival on January 6, 2025, no information on recent outbreaks is available. 2) Videos have not been restored. 3) Go to <a href="https://data.restoredcdc.org">data.restoredcdc.org</a>(folder organization on-going) to access restored data. 4) Use of this site implies acceptance of this disclaimer.</p>
  </div>
  <div style="display: flex; flex-direction: column; gap: 5px; flex-shrink: 0;text-align: center; font-size: 0.8em">
    <a href="https://aboutus.restoredcdc.org/mission" target="_blank" style="padding: 8px 15px; font-weight: bold; background: #2A1E5C; color: white; text-decoration: none; border-radius: 5px;">About RestoredCDC.org</a>
    <a href="https://bugs.restoredcdc.org" style="padding: 8px 15px; font-weight: bold; background: #2A1E5C; color: white; text-decoration:none; border-radius: 5px" target="_blank">Report a Problem</a>
  </div>
</div>
'''

desktop_search_pattern = re.compile(r'<form id="cdc-desktop-search-form".*?</form>', re.DOTALL)

desktop_search_replace = '''
<form id="cdc-desktop-search-form" class="cdc-header-search-form" role="search" onsubmit="return false;">
    <input class="form-control" type="search" name="q" data-search-input aria-label="Search" placeholder="Search (Disabled)" disabled title="Search is currently disabled.">
    <button type="submit" disabled title="Search is disabled"><span class="cdc-fa-magnifying-glass"></span></button>
    <button type="button" title="Search is disabled"><span class="cdc-icon-close"></span></button>
</form>

'''

sticky_search_pattern = re.compile(r'<form id="sticky-cdc-desktop-search-form".*?</form>', re.DOTALL)

sticky_search_replace = '''
<form id="sticky-cdc-desktop-search-form" class="cdc-header-search-form" role="search" onsubmit="return false;">
    <input class="form-control" type="search" name="q" data-search-input aria-label="Search" placeholder="Search (Disabled)" disabled title="Search is currently disabled.">
    <button type="submit" disabled title="Search is disabled"><span class="cdc-fa-magnifying-glass"></span></button>
    <button type="button" title="Search is disabled"><span class="cdc-icon-close"></span></button>
</form>

'''


mobile_search_pattern = re.compile(r'<form id="cdc-mobile-search-form".*?</form>',re.DOTALL)

mobile_search_replace = '''
<form id="cdc-mobile-search-form" class="cdc-header-search-form" role="search" onsubmit="return false;">
    <input class="form-control" type="search" name="q" data-search-input aria-label="Search" placeholder="Search (Disabled)" disabled title="Search is currently disabled.">
    <button type="submit" disabled title="Search is disabled"><span class="cdc-fa-magnifying-glass"></span></button>
    <button type="button" title="Search is disabled"><span class="cdc-icon-close"></span></button>
</form>

'''

search_override = '''
<script>
document.addEventListener("DOMContentLoaded", function () {
    setTimeout(function () {
        if (window.CDC_CONFIG) {
            // Override search URL globally
            window.CDC_CONFIG.search_url = "https://www.google.com/search";
        }

        // Fix all search forms
        var searchForms = [
            document.querySelector('#cdc-desktop-search-form'),
            document.querySelector('#cdc-mobile-search-form'),
            document.querySelector('#sticky-cdc-desktop-search-form')
        ];

        searchForms.forEach(form => {
            if (form) {
                // Force the correct search action
                form.action = "https://www.google.com/search";

                // Ensure the search input field uses "q" for Google
                if (form.querySelector('[type="search"]')) {
                    form.querySelector('[type="search"]').name = "q";
                }

                console.log("Fixed search form action for:", form.id);
            }
        });
    }, 1000); // Wait longer to ensure CDC scripts load first
});
</script>

'''

# we need the root of the site to be /www.cdc.gov/ so if our domain is
# www.example.com when someone visits www.example.com we need to redirect
# them to www.example.com/www.cdc.com/ subfolder. the home route ensures that.


@app.route("/")
def home():
  return redirect("/www.cdc.gov/")

# Catch-all route
# from here we will collect the path requested after www.example.com
# and look for it in the database so if a request for www.example.com/www.cdc.gov/something/image.jpg
# is requested, here we capture /www.cdc.gov/something/image.jpg part of it, remove the first / character
# then search for the remaining path in database, get its data and type from the database
# and serve it back directly.

@app.route('/<path:subpath>')
def lookup(subpath):

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
      # here we add the disclaimer with a regex if the request is for a html file.
      content = body_tag_regex.sub(r'\1' + DISCLAIMER_HTML, content, count=1)
      # and replace the official notice
      content = content.replace("An official website of the United States government","")
      content = re.sub(re.escape("$NAME"),subpath, content, count = 1)
      content = re.sub(logo_pattern,"",content)
      content = re.sub(svg_pattern,"",content)
      content = content.replace("Centers for Disease Control and Prevention. CDC twenty four seven. Saving Lives, Protecting People","")
      content = content.replace('alt="Centers for Disease Control and Prevention"',"")
      content = content.replace('alt="U.S. flag"',"")
      content = content.replace('hp2024.js',"")
      content = content.replace('id="cdc-footer-nav"','id="cdc-footer-nav" style="display:block !important;"')
      content = re.sub(nav_pattern, nav_replace, content, count=1)
      content = content.replace('<title>','<title>Restored CDC | ')
      content = content.replace('href="https://www.cdc.gov', 'href="https://www.restoredcdc.org')
      content = re.sub(desktop_search_pattern, desktop_search_replace, content)
      content = re.sub(sticky_search_pattern, sticky_search_replace, content)
      content = re.sub(mobile_search_pattern, mobile_search_replace, content)
    #  content = re.sub(body_end_tag_regex, search_override + "\n</body>", content)
    # if the path was not a redirect, serve the content directly along with its mimetype
    # the browser will know what to do with it.
    return Response(content, mimetype=mimetype)
  except Exception as e:
    # if anything is wrong, just send a 404
    # print(f"Error retrieving {full_path}: {e}")
    # return Response("404 Not Found", status=404, mimetype="text/plain")
    # return render_template("404.html", error=str(e)), 404 
    return render_template('404.html'), 404

if __name__ == '__main__':
  print(f"Starting cdcmirror server process at port {serverPort}")
  serve(app, host=hostName, port=serverPort)
