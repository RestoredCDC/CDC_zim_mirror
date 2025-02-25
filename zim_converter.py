# converts a zim capture of a web page to LevelDB format
# batuhan@earslap.com
import libzim
import plyvel

# load the zim archive from the working directory
arch = libzim.Archive(r"./www.cdc.gov_en_all_novid_2025-01.zim")

# create the LevelDB database in the working directory under ./cdc_database
# this database will contain the entire link path -> response pairs
# so the entire contents of the website
db = plyvel.DB('./cdc_database', create_if_missing=True)

# each piece of captured data in the database is a byte sequence.
# we don't necessarily know its type.
# .zim file has the mimetype of the data as returned by the server
# captured during original crawl. we keep the data byte sequence
# and its corresponding type (mimetype) in different "tables"
# in practice, they will be stored in the database with c- (for content)
# and m- prefixes. so in the key-value scheme, the contents of www.example.com/
# will be stored in key "c-www.example.com/" and its mimetype ("text/html")
# will be stored in "m-www.example.com/"
content_db = db.prefixed_db(b"c-")
mimetype_db = db.prefixed_db(b"m-")

count = arch.all_entry_count  # number of all entries in the zim file
errors = []  # we will accumulate errors here and print them in the end to see which URLs are affected

# enumerate all content in the .zim file
for i in range(0, count):
  print(f"{i}/{count}")  # print progress

  # getting id this way is undocumented, found it in a github issue
  original_entry = arch._get_entry_by_id(i)

  # some entries are redirects to other items (because the server
  # redirected to another URL during crawl) we will follow and resolve
  # all redirects soon, we need to keep the originating URL/path
  # so that we can link the source to redirected target
  original_path = original_entry.path

  try:
    # get the entry for the original path
    entry = arch.get_entry_by_path(original_path)
    redirect_detected = False

    # if entry is a redirect:
    # follow all redirects recursively to reach the final target
    # if the .zim is not well formed and there are redirect loops
    # this might hang so beware. we are only interested in the final
    # redirection target and not in the intermediate ones
    while entry.is_redirect:
      print(f"Redirect detected from: {entry.path}")  # logging for debugging
      # we will use this later to put a special redirect value in database
      redirect_detected = True
      entry = entry.get_redirect_entry()  # hop entry to the next redirect
      print(f"To: {entry.path}")  # logging for debugging

    if redirect_detected:  # if at least one redirect was detected
      # this is a hack, but instead of storing the mimetype, use a special token
      # to signify we are not storing data, but the redirection target
      mime = "=redirect="
      source_path = original_path
      target_path = entry.path
      print(
          f"Putting redirect to database: {source_path}   --->   {target_path}")
      # instead of storing data in content, we store the target path as string
      content_db.put(bytes(source_path, "UTF-8"), bytes(target_path, "UTF-8"))
      # instead of storing mimetype for data (which we don't have) we store
      # the special "=redirect=" token
      mimetype_db.put(bytes(source_path, "UTF-8"), bytes(mime, "UTF-8"))
    else:  # if there are no redirects
      # get the contents of entry. get_item normally follows all redirects
      # automatically but we are guaranteed to not be in a redirect here
      item = entry.get_item()
      mime = item.mimetype
      path = entry.path
      content = item.content

      # store the data and mimetype for data
      content_db.put(bytes(path, "UTF-8"), bytes(content))
      mimetype_db.put(bytes(path, "UTF-8"), bytes(mime, "UTF-8"))
  # except Exception as e:
  except Exception as e:
    print(f"error: {original_path}")
    print(f"error message: {e}")
    errors.append(original_path)

# print all paths that encountered an error
# this might be due to malformed .zim file, for instance
# or bugs in the above code
print(errors)
db.close()

print("done!")
