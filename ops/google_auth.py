#!/usr/bin/env python3
"""Conecta o Lolo ao Google (Calendar + Tasks + Gmail + Drive).

1) Coloque o client OAuth "App para computador" em data/google_client_secret.json (Google Cloud: ative Google Calendar API,
   Google Tasks API, Gmail API e Google Drive API).
2) python3 ops/google_auth.py url      -> imprime o link; abra, aceite com a conta do Paulo. O navegador vai mostrar uma
   página de erro em http://localhost:1/?code=...; copie a URL inteira (ou só o code).
3) python3 ops/google_auth.py code "<URL ou code>"  -> grava data/google_token.json (permissão 600).
"""
import json
import os
import sys
import urllib.parse
import urllib.request

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
CLIENT, TOKEN = os.path.join(D, "google_client_secret.json"), os.path.join(D, "google_token.json")
SCOPES = ("https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/tasks "
          "https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/gmail.compose "
          "https://www.googleapis.com/auth/drive")
REDIRECT = "http://localhost:1/"


def client():
    raw = json.load(open(CLIENT, encoding="utf-8"))
    return raw.get("installed") or raw.get("web") or raw


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("url", "code"):
        print(__doc__)
        return 2
    c = client()
    if sys.argv[1] == "url":
        q = urllib.parse.urlencode({"client_id": c["client_id"], "redirect_uri": REDIRECT, "response_type": "code",
                                    "scope": SCOPES, "access_type": "offline", "prompt": "consent"})
        print("https://accounts.google.com/o/oauth2/v2/auth?" + q)
        return 0
    raw = sys.argv[2]
    code = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query).get("code", [raw])[0]
    data = urllib.parse.urlencode({"code": code, "client_id": c["client_id"], "client_secret": c["client_secret"],
                                   "redirect_uri": REDIRECT, "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=data), timeout=30) as r:
        tok = json.loads(r.read())
    if "refresh_token" not in tok:
        print("Sem refresh_token: refaça o passo 'url' (prompt=consent) e autorize de novo.")
        return 1
    import time
    tok["expiry"] = time.time() + int(tok.get("expires_in", 3500))
    json.dump(tok, open(TOKEN, "w", encoding="utf-8"))
    os.chmod(TOKEN, 0o600)
    try:
        if os.geteuid() == 0:
            st = os.stat(D)
            os.chown(TOKEN, st.st_uid, st.st_gid)
    except OSError:
        pass
    print("Google conectado: token gravado em data/google_token.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
