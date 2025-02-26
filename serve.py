from urllib import parse
from flask import Flask, Response, redirect
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
hostName = "0.0.0.0"
serverPort = 9090

# we will use the following regex to add a disclaimer after the body tag 
body_tag_regex = re.compile(r'(<body\b[^>]*>)', re.IGNORECASE)
# this disclaimer will be at the top of every page.
DISCLAIMER_HTML = '''
<div style="background:yellow; padding:10px; text-align:center;">
  Disclaimer: This is a demo disclaimer.
</div>
'''

# due to the way the database routing and relative paths within it work
# we need the "root" of the site to be /www.cdc.gov/ so if our domain is
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
    print(f"Request for: {full_path}")
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
    
    # here we add the disclaimer with a regex if the request is for a html file.
    if mimetype.startswith("text/html"):
      content = content.decode("utf-8")
      content = body_tag_regex.sub(r'\1' + DISCLAIMER_HTML, content, count=1)

    # if the path was not a redirect, serve the content directly along with its mimetype
    # the browser will know what to do with it.
    return Response(content, mimetype=mimetype)
  except Exception as e:
    # if anything is wrong, just send a 404
    print(f"Error retrieving {full_path}: {e}")
    return Response("404 Not Found", status=404, mimetype="text/plain")


if __name__ == '__main__':
  serve(app, host=hostName, port=serverPort)
