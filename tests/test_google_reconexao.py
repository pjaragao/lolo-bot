"""Google desconectado: o aviso com o link no WhatsApp e a volta do endereço (offline, Google e WhatsApp simulados).
   HERMES_HOME=/tmp/lolotest-g JOY_DIR=/home/paulojr/lolo-bot/joy python3 -I tests/test_google_reconexao.py
"""
import io
import json
import os
import shutil
import sys
import urllib.error

assert os.environ.get("HERMES_HOME", "").startswith("/tmp"), "use HERMES_HOME=/tmp/... (nunca o real)"
H = os.environ["HERMES_HOME"]
shutil.rmtree(H, ignore_errors=True)
os.makedirs(H)
sys.path.insert(0, os.environ.get("JOY_DIR", "/opt/joy"))
json.dump({"installed": {"client_id": "cid", "client_secret": "sec"}}, open(os.path.join(H, "google_client_secret.json"), "w"))
json.dump({"refresh_token": "old", "access_token": "x", "expiry": 0}, open(os.path.join(H, "google_token.json"), "w"))

import carreira  # noqa: E402
import core  # noqa: E402
import google  # noqa: E402
import lembretes  # noqa: E402

sent = []
lembretes._enviar = lambda t: sent.append(t) or True
google_answers = []


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(req, timeout=0):
    a = google_answers.pop(0)
    if isinstance(a, int):
        raise urllib.error.HTTPError(req.full_url, a, "Bad Request", {}, io.BytesIO(b'{"error":"invalid_grant"}'))
    return Resp(json.dumps(a).encode())


google.urllib.request.urlopen = fake_urlopen

# 1) the refresh is refused: a clear error and one message with the link
google_answers.append(400)
try:
    google._access_token()
    raise AssertionError("devia falhar")
except google.AcessoExpirado:
    pass
assert len(sent) == 1 and "Google desconectado" in sent[0] and "accounts.google.com/o/oauth2/v2/auth?" in sent[0] and "client_id=cid" in sent[0]
assert "prompt=consent" in sent[0] and "access_type=offline" in sent[0]

# 2) failing again in the next hours does not repeat the message
google_answers.append(400)
try:
    google._access_token()
except google.AcessoExpirado:
    pass
assert len(sent) == 1
assert google.avisar_reconexao("x", agora=__import__("time").time() + 7 * 3600)   # after 6 hours, once more
assert len(sent) == 2

# 3) the address sent back is a direct command, case kept
URL = "http://localhost:1/?iss=https://accounts.google.com&code=4/0AbC-xYz_9&scope=https://www.googleapis.com/auth/drive%20x"
assert carreira.comando(URL) == ("carreira_google", {"endereco": URL})
assert carreira.comando("localhost:1/?code=4/0AbC") == ("carreira_google", {"endereco": "localhost:1/?code=4/0AbC"})
assert carreira.comando("o link http://localhost:1/?code=abc deu erro?") is None   # a sentence goes to the model

# 4) a used or expired code: says so with a new link, the token is not touched
google_answers.append(400)
r = google.reconectar(URL)
assert "recusou esse código" in r and "accounts.google.com" in r
assert json.load(open(os.path.join(H, "google_token.json")))["refresh_token"] == "old"

# 5) the good code: new token saved, the warning cleared, and the e-mail reading runs right after
google_answers.append({"access_token": "new", "refresh_token": "fresh", "expires_in": 3600})
carreira.email_tick = lambda: "carreira-email: 3 lido(s), 1 novo(s) sobre candidaturas, 0 arquivado(s)"
out = core.run_query("carreira_google", {"endereco": URL})
assert out.startswith("✅ Google reconectado.") and "3 lido(s)" in out, out
tok = json.load(open(os.path.join(H, "google_token.json")))
assert tok["refresh_token"] == "fresh" and tok["access_token"] == "new" and tok["expiry"] > 0
assert not os.path.exists(google.AVISO_FILE)
assert google._access_token() == "new"   # no more refreshes needed

# 6) the code exchange got the code out of the address, with the same redirect
print("ok: test_google_reconexao")
