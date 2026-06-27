How to add cookies for sites that block automatic cookie extraction
====================================================================

Modern Edge/Chrome (v127+) encrypt cookies with "App-Bound Encryption",
which the browser_cookie3 library can't decrypt — not even when running
as Administrator. The fix is to export cookies manually once and drop
them in this folder.

Steps (using the free "Cookie-Editor" extension):
  1. Install "Cookie-Editor" from the Edge/Chrome Web Store.
  2. Log in / browse normally on the target site (e.g. de.indeed.com)
     so you have valid session cookies.
  3. Click the Cookie-Editor toolbar icon, click "Export" -> "Export as JSON"
     (this copies the cookies to your clipboard as a JSON array).
  4. Paste that JSON into a new file in this folder named after the site's
     cookie domain, for example:

         scraper/cookies/.indeed.com.json

     (Note the leading dot — that's the cookie domain Indeed uses.)

  5. Re-run a refresh. The scraper will automatically pick up this file
     instead of trying (and failing) to read cookies from the browser.

Supported formats:
  - JSON array:  [{"name": "...", "value": "...", "domain": "...", "path": "/"}, ...]
    (this is exactly what Cookie-Editor's "Export as JSON" produces)
  - Netscape cookies.txt (tab-separated), saved with a ".txt" extension —
    produced by extensions like "Get cookies.txt LOCALLY".

Cookies do expire — if scraping starts failing again with an auth/blocked
error after a while, just repeat the export to refresh the file.
