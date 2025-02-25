from urllib import parse
from flask import Flask, Response, redirect
from waitress import serve
import plyvel

db = plyvel.DB('./cdc_database')
content_db = db.prefixed_db(b"c-")
mimetype_db = db.prefixed_db(b"m-")

app = Flask(__name__)

hostName = "0.0.0.0"
serverPort = 9090

@app.route("/")
def home():
  return redirect("/www.cdc.gov/")

# Catch-all route
@app.route('/<path:subpath>')
def hello(subpath):
  full_path = parse.unquote(subpath)
  print(f"Request for: {full_path}")

  try:
    content = content_db.get(bytes(full_path, "UTF-8"))
    mimetype = mimetype_db.get(bytes(full_path, "UTF-8")).decode("utf-8")
    if mimetype == "=redirect=":
      return redirect(f'/{content.decode("utf-8")}')

    return Response(content, mimetype=mimetype)
  except Exception as e:
    print(f"Error retrieving {full_path}: {e}")
    return Response("404 Not Found", status=404, mimetype="text/plain")


if __name__ == '__main__':
  serve(app, host=hostName, port=serverPort)
