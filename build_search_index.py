"""
build_search_index.py
---------------------
Creates a Whoosh search index from the content in a LevelDB database.
This script:
  - Retrieves HTML entries from the 'cdc_database'
  - Normalizes paths
  - Parses out main text via BeautifulSoup
  - Deduplicates multiple entries for the same normalized path
  - Commits documents to the 'search_index' directory
"""

import os
import plyvel
import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning, MarkupResemblesLocatorWarning
from bs4.exceptions import ParserRejectedMarkup
from whoosh.index import create_in
from whoosh.fields import Schema, TEXT, ID
from whoosh.analysis import StemmingAnalyzer
from tqdm import tqdm  # progress bar library

# import sys
# Optional: increase recursion limit if needed
# sys.setrecursionlimit(5000)

# Suppress specific warnings from BeautifulSoup's parser
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)


def normalize_path(raw_path):
    """
    Normalize the URL path by:
      - Converting to lowercase
      - Removing any query string (anything after '?')
      - Stripping trailing slashes (unless it's the root)
      - Removing '/index.html' or '/index.htm' if present

    Returns the normalized path as a string.
    """
    path = raw_path.lower()

    # Remove query string if present
    if "?" in path:
        path = path.split("?", 1)[0]

    # Remove trailing slash, except if path == "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Remove specific index pages
    if path.endswith("/index.html"):
        path = path[: -len("/index.html")]
    elif path.endswith("/index.htm"):
        path = path[: -len("/index.htm")]

    return path


# Define our Whoosh schema for indexing
schema = Schema(
    path=ID(unique=True, stored=True),
    title=TEXT(stored=True),
    # 'spelling=True' stores unmodified terms, helpful for suggestions
    content=TEXT(stored=True, analyzer=StemmingAnalyzer(), spelling=True),
)

# Create or open the index directory
if not os.path.exists("search_index"):
    os.mkdir("search_index")

ix = create_in("search_index", schema)
writer = ix.writer()

# Open the LevelDB database (converted .zim)
db = plyvel.DB("./cdc_database")
content_db = db.prefixed_db(b"c-")
mimetype_db = db.prefixed_db(b"m-")

processed = 0
skipped = 0

print("Counting total number of documents in DB for progress…")
total_docs = sum(1 for _ in content_db)
print(f"Total docs in DB: {total_docs}")

# We'll track normalized paths to handle duplicates
# e.g. dedup_dict[norm] = (raw_path, length_of_raw)
dedup_dict = {}

# Progress bar for clarity
progress_bar = tqdm(
    content_db, total=total_docs, unit="doc", desc="Indexing documents", mininterval=10
)

for key, value in progress_bar:
    raw_path = key.decode("utf-8", errors="ignore")
    norm = normalize_path(raw_path)

    # Check mimetype; skip if not HTML
    mime_val = mimetype_db.get(key)
    if not mime_val:
        skipped += 1
        continue
    mime_str = mime_val.decode("utf-8", errors="ignore").lower()
    if not mime_str.startswith("text/html"):
        skipped += 1
        continue

    # Decode the HTML content
    html = value.decode("utf-8", errors="replace")

    # Attempt to parse with BeautifulSoup
    try:
        soup = BeautifulSoup(html, "lxml")
    except ParserRejectedMarkup:
        tqdm.write(f"Parser rejected {raw_path}, skipping.")
        skipped += 1
        continue
    except Exception as e:
        tqdm.write(f"Skipping {raw_path} due to parse error: {e}")
        skipped += 1
        continue

    # Extract a title (truncated to 300 chars)
    raw_title = soup.title.string if (soup.title and soup.title.string) else ""
    title_str = raw_title[:300]

    # Try to find <main> to avoid repeated headers/footers
    main_content = soup.find("main", class_="container cdc-main")
    if not main_content:
        # Fallback to entire page if <main> is missing
        main_content = soup

    # Remove script/style tags from main content
    for tag in main_content(["script", "style"]):
        tag.decompose()

    # Extract text
    text_str = main_content.get_text(separator=" ", strip=True)
    if not text_str.strip():
        skipped += 1
        continue

    # Deduplicate docs based on normalized path
    new_len = len(raw_path)
    if norm in dedup_dict:
        old_raw, old_len = dedup_dict[norm]
        if new_len < old_len:
            # If the new path is shorter, replace the older doc in the index
            writer.delete_by_term("path", old_raw)
            writer.update_document(path=raw_path, title=title_str, content=text_str)
            dedup_dict[norm] = (raw_path, new_len)
        else:
            # Otherwise skip this doc
            skipped += 1
            continue
    else:
        # First time we see this normalized path
        writer.update_document(path=raw_path, title=title_str, content=text_str)
        dedup_dict[norm] = (raw_path, new_len)

    processed += 1
    progress_bar.update(1)

writer.commit()
db.close()

print(
    f"Indexing complete. Processed {processed} documents; skipped {skipped} documents."
)
