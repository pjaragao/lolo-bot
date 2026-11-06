"""Testes offline de rascunho, anexo e envio de e-mail (Gmail simulado em memória). Reproduz o incidente de 30/10: o Paulo manda a
NF e pede para juntar ao e-mail pronto e enviar → o Lolo tem de anexar o PDF original a ESSE rascunho, sem criar outro.
   HERMES_HOME=/tmp/lolotest JOY_DIR=/home/paulojr/lolo-bot/joy python3 -I tests/test_email.py
"""
import base64
import email
import email.message
import email.policy
import json
import os
import shutil
import sys

assert os.environ.get("HERMES_HOME", "").startswith("/tmp"), "use HERMES_HOME=/tmp/... (nunca o real)"
shutil.rmtree(os.environ["HERMES_HOME"], ignore_errors=True)
os.makedirs(os.environ["HERMES_HOME"])
os.environ.pop("AGY_SHIM_TOKEN", None)
sys.path.insert(0, os.environ.get("JOY_DIR", "/opt/joy"))

import arquivos  # noqa: E402
import core  # noqa: E402
import gmail  # noqa: E402
import google  # noqa: E402

THREAD, RESPONDIDO = "thread-sa", "msg-jefferson"


# --------------------------------------------------------------------------- Gmail falso
class FakeGmail:
    def __init__(self):
        self.drafts, self.enviados, self.n = {}, [], 0

    def api(self, method, url, body=None, params=None):
        rota = url.replace(gmail.BASE, "")
        if method == "GET" and rota == "/drafts":
            q = ((params or {}).get("q") or "").lower()
            return {"drafts": [{"id": i, "message": {"id": f"m{i}", "threadId": d["thread"]}} for i, d in self.drafts.items()
                               if q in d["raw"].decode("utf-8", "replace").lower()]}
        if method == "GET" and rota.startswith("/drafts/"):
            d = self.drafts[rota.split("/")[2]]
            return {"message": {"raw": base64.urlsafe_b64encode(d["raw"]).decode(), "threadId": d["thread"]}}
        if method == "POST" and rota == "/drafts/send":
            self.enviados.append(self.drafts.pop(body["id"]))
            return {"id": "enviado"}
        if method == "GET" and rota == f"/messages/{RESPONDIDO}":
            return {"id": RESPONDIDO, "threadId": THREAD, "payload": {"headers": [{"name": "Message-ID", "value": "<orig@sa>"}]}}
        raise AssertionError(f"rota inesperada: {method} {url}")

    def urlopen(self, req, timeout=None):
        """O endpoint de upload: multipart/related com o JSON e a mensagem inteira."""
        assert "/upload/gmail/" in req.full_url and "uploadType=multipart" in req.full_url, req.full_url
        boundary = req.get_header("Content-type").split("boundary=")[1]
        _antes, meta, raw = req.data.split(f"--{boundary}".encode())[:3]
        thread = json.loads(meta.split(b"\r\n\r\n", 1)[1])["message"].get("threadId")
        raw = raw.split(b"\r\n\r\n", 1)[1][:-2]
        if req.get_method() == "PUT":
            did = req.full_url.split("/drafts/")[1].split("?")[0]
            assert did in self.drafts, did
        else:
            self.n += 1
            did = f"r{self.n}"
        self.drafts[did] = {"raw": raw, "thread": thread}
        resposta = json.dumps({"id": did}).encode()

        class R:
            status = 200

            def read(self):
                return resposta

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False
        return R()

    def msg(self, did):
        return email.message_from_bytes(self.drafts[did]["raw"], policy=email.policy.default)


FG = FakeGmail()
google._api = FG.api
google.conectado = lambda: True
google._access_token = lambda: "token"
gmail.urllib.request.urlopen = FG.urlopen

PDF = b"%PDF-1.7\n" + bytes(range(256)) * 40
arquivos.save_inbox(PDF, "42054072214596598000138000000000000226100605743528.pdf", mime="application/pdf",
                    sender="Paulo", kind="document", extra={"texto": "DANFSe NFS-e 2 S.A. Paulista"})

TEXTO = "Olá Flavio e Jefferson,\n\nA Nota Fiscal correspondente segue em anexo.\n\nAtenciosamente,\nPaulo"
ORIGEM = {"para": "user@example.com", "assunto": "Re: Pagamento NF Consultoria", "corpo": TEXTO, "responder_id": RESPONDIDO}

# 1. rascunho sem arquivo diz que está sem anexo e avisa quando o texto promete um
r = core.run_query("email_rascunho", dict(ORIGEM))
assert "Rascunho criado" in r and "Sem anexo" in r and "⚠️" in r, r
assert list(FG.drafts) == ["r1"] and FG.drafts["r1"]["thread"] == THREAD

# 2. o Lolo acha o rascunho que ele mesmo deixou pronto
r = core.run_query("email_rascunhos", {"busca": "example"})
assert "r1" in r and "user@example.com" in r and "segue em anexo" in r, r
assert core.run_query("email_rascunhos", {"busca": "ninguem"}) == "Nenhum rascunho encontrado."

# 3. não cria um segundo rascunho na mesma conversa (o que aconteceu em 30/10)
r = core.run_query("email_rascunho", {**ORIGEM, "para": "user@example.com"})
assert r.startswith("⛔") and "r1" in r and list(FG.drafts) == ["r1"], r

# 4. não envia sem confirmação, nem "segue em anexo" sem o arquivo
assert "falta a confirmação" in core.run_query("email_enviar", {"id": "r1"})
r = core.run_query("email_enviar", {"id": "r1", "confirmado": True})
assert r.startswith("⛔ Não enviei") and "email_anexar" in r and not FG.enviados, r

# 5. anexar exige o id e um arquivo que exista; falha não mexe no rascunho
assert "Informe o id" in core.run_query("email_anexar", {"anexo": "ultimo"})
antes = FG.drafts["r1"]["raw"]
r = core.run_query("email_anexar", {"id": "r1", "anexo": "boleto inexistente"})
assert "não achei" in r and FG.drafts["r1"]["raw"] == antes, r

# 6. anexa o PDF ORIGINAL no MESMO rascunho, sem mudar texto, destinatário nem conversa
r = core.run_query("email_anexar", {"id": "r1", "anexo": "ultimo"})
assert "📎 Anexado" in r and "42054072214596598000138000000000000226100605743528.pdf" in r and "📎 Anexos:" in r, r
m = FG.msg("r1")
assert list(FG.drafts) == ["r1"] and FG.drafts["r1"]["thread"] == THREAD
assert m["To"] == "user@example.com" and m["Subject"] == ORIGEM["assunto"] and m["In-Reply-To"] == "<orig@sa>"
assert TEXTO in m.get_body(("plain",)).get_content().replace("\r\n", "\n")
anexos = list(m.iter_attachments())
assert len(anexos) == 1 and anexos[0].get_content() == PDF and anexos[0].get_content_type() == "application/pdf"

# 7. repetir não duplica; a busca por parte do nome também acha o arquivo
r = core.run_query("email_anexar", {"id": "r1", "busca": "4205407221"})
assert "já estava anexado" in r and len(list(FG.msg("r1").iter_attachments())) == 1, r

# 8. mudar o texto ou o destinatário mantém o rascunho, a conversa e o anexo
r = core.run_query("email_rascunho", {"id": "r1", "para": "user@example.com", "cc": "user@example.com",
                                      "corpo": "Olá Jefferson,\n\nSegue em anexo a NF nº 2.\n\nPaulo"})
assert "Rascunho atualizado" in r and "⚠️" not in r and "📎 Anexos:" in r, r
m = FG.msg("r1")
assert list(FG.drafts) == ["r1"] and FG.drafts["r1"]["thread"] == THREAD
assert m["To"] == "user@example.com" and m["Cc"] == "user@example.com" and m["Subject"] == ORIGEM["assunto"]
assert m["In-Reply-To"] == "<orig@sa>" and "NF nº 2" in m.get_body(("plain",)).get_content() and "Flavio e" not in m.as_string()
assert [a.get_content() for a in m.iter_attachments()] == [PDF]

# 9. o envio confirmado sai com o arquivo e diz para quem e com o quê
r = core.run_query("email_enviar", {"id": "r1", "confirmado": True})
assert r.startswith("📤") and "user@example.com" in r and "42054072214596598000138000000000000226100605743528.pdf" in r, r
assert not FG.drafts and len(FG.enviados) == 1 and FG.enviados[0]["thread"] == THREAD
assert PDF in [a.get_content() for a in email.message_from_bytes(FG.enviados[0]["raw"], policy=email.policy.default).iter_attachments()]

# 10. pedido novo de verdade pode criar outro rascunho, e "vai sem arquivo" só passa com forcar
core.run_query("email_rascunho", dict(ORIGEM))
r = core.run_query("email_rascunho", {**ORIGEM, "forcar": True})
assert "Rascunho criado" in r and len(FG.drafts) == 2, r
did = next(iter(FG.drafts))
r = core.run_query("email_enviar", {"id": did, "confirmado": True, "forcar": True})
assert r.startswith("📤") and "Sem anexo" in r, r
FG.drafts.clear()

# 11. e-mail direto (sem rascunho prévio) também leva anexo; texto sem promessa de anexo sai normal
n = len(FG.enviados)
r = core.run_query("email_enviar", {"confirmado": True, "para": "user@example.com", "assunto": "NF", "corpo": "Segue em anexo.", "anexo": "ultimo"})
assert r.startswith("📤") and ".pdf" in r and len(FG.enviados) == n + 1, r
r = core.run_query("email_enviar", {"confirmado": True, "para": "user@example.com", "assunto": "Oi", "corpo": "Tudo certo por aqui."})
assert r.startswith("📤") and "Sem anexo" in r and len(FG.enviados) == n + 2, r

# 12. rascunho escrito no Gmail (texto + HTML + imagem da assinatura) não perde nada; assinatura não conta como anexo
g = email.message.EmailMessage()
g["To"], g["Subject"] = "user@example.com", "Do Gmail"
g.set_content("Segue em anexo a planilha")
g.add_alternative("<p>Segue em <b>anexo</b> a planilha</p>", subtype="html")
g.add_attachment(b"\x89PNG", maintype="image", subtype="png", filename="image001.png", disposition="inline")
FG.drafts["gm"] = {"raw": g.as_bytes(), "thread": "t-gm"}
assert gmail.ver_rascunho("gm")["anexos"] == []
assert core.run_query("email_enviar", {"id": "gm", "confirmado": True}).startswith("⛔"), "assinatura não vale como anexo"
arquivos.save_inbox(b"PK-planilha", "Medição de obra nº 2.xlsx", mime="application/vnd.ms-excel", sender="Paulo", kind="document",
                    ts=9_999_999_999)
r = core.run_query("email_anexar", {"id": "gm", "anexo": "medicao obra"})
assert "Medição de obra nº 2.xlsx" in r, r
m = FG.msg("gm")
assert FG.drafts["gm"]["thread"] == "t-gm"
assert "planilha" in m.get_body(("plain",)).get_content() and "<b>anexo</b>" in m.get_body(("html",)).get_content()
assert [a.get_filename() for a in m.iter_attachments() if a.get_content_disposition() != "inline"] == ["Medição de obra nº 2.xlsx"]
FG.drafts.clear()

# 13. dois arquivos numa chamada só
r = core.run_query("email_rascunho", {"para": "user@example.com", "assunto": "Dois", "corpo": "Oi", "anexo": "42054072214596598; medicao"})
did = r.split("Rascunho ")[-1].split(" ")[0]
assert len(list(FG.msg(did).iter_attachments())) == 2, r
FG.drafts.clear()

# 14. acima do limite do Gmail vira erro claro, sem deixar rascunho pela metade
gmail.MAX_MENSAGEM = 1000
r = core.run_query("email_rascunho", {"para": "user@example.com", "assunto": "Grande", "corpo": "Oi", "anexo": "42054072214596598"})
assert "limite do Gmail" in r and not FG.drafts, r
gmail.MAX_MENSAGEM = 25 * 1024 * 1024

# 15. a trava olha o que está sendo escrito agora, não o que está citado de e-mails anteriores
assert gmail.cita_anexo("Segue em anexo a NF") and gmail.cita_anexo("Vai anexa a planilha") and gmail.cita_anexo("See the attached file")
assert gmail.cita_anexo("Documento anexado.") and not gmail.cita_anexo("Tudo certo, obrigado!")
assert not gmail.cita_anexo("Recebido, obrigado.\n\nEm qua., 23 de set. de 2026, 11:25, Paulo escreveu:\n> Segue em anexo a NF")
assert not gmail.cita_anexo("Recebido.\n> Segue em anexo a NF")

print("OK — email")
