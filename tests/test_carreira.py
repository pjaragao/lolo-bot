"""Testes offline da ponte com o CareerOps (API e WhatsApp simulados).
   HERMES_HOME=/tmp/lolotest JOY_DIR=/home/paulojr/lolo-bot/joy python3 -I tests/test_carreira.py
"""
import os
import shutil
import sys

assert os.environ.get("HERMES_HOME", "").startswith("/tmp"), "use HERMES_HOME=/tmp/... (nunca o real)"
shutil.rmtree(os.environ["HERMES_HOME"], ignore_errors=True)
os.makedirs(os.environ["HERMES_HOME"])
os.environ["CAREEROPS_BOT_TOKEN"] = "t"
sys.path.insert(0, os.environ.get("JOY_DIR", "/opt/joy"))

import carreira  # noqa: E402
import core  # noqa: E402
import google  # noqa: E402
import lembretes  # noqa: E402
import midia  # noqa: E402


class FakeApi:
    def __init__(self):
        self.calls, self.notes, self.acked, self.archived = [], [], [], []
        self.proposed = {"apply": [{"id": 3}, {"id": 4}], "comment": [{"id": 7}],
                         "items": [{"id": 3, "kind": "apply"}, {"id": 4, "kind": "apply"}, {"id": 7, "kind": "comment"}]}
        self.mode = "live"

    def __call__(self, method, path, body=None, timeout=30, raw=False):
        self.calls.append((method, path, body))
        if path.endswith("/approve"):
            i = int(path.split("/")[-2])
            if i == 99:
                raise carreira.Erro("CareerOps 404: Não encontrado")
            return {"id": i, "status": "approved" if i in (3, 4) else "queued"}
        if path.endswith("/revise"):
            return {"id": 9, "title": "Ana", "payload": {"author": "Ana", "text": "Versão curta"}}
        if path == "/automation/running":
            return {"items": [
                {"id": 50, "kind": "comment", "status": "queued", "run_now": False, "title": "Gabriel",
                 "target_url": "https://www.linkedin.com/posts/gabriel-1", "payload": {"author": "Gabriel Rodrigues", "post_head": "Precificar"}},
                {"id": 51, "kind": "comment", "status": "running_ext", "payload": {}}]}
        if path == "/automation/history":
            return {"items": [
                {"id": 40, "kind": "comment", "status": "done", "finished_at": "2026-11-03T01:15:43+00:00", "title": "Ricardo",
                 "target_url": "https://www.linkedin.com/posts/ricardo-1", "payload": {"author": "Ricardo Martins", "text": "Como você garantiu isso?",
                                                                                     "post_head": "\nAutomação de currículos com IA\nresto"}},
                {"id": 41, "kind": "comment", "status": "cancelled", "payload": {"author": "X", "text": "não saiu"}},
                {"id": 42, "kind": "follow", "status": "done", "finished_at": "2026-11-02T12:00:00+00:00", "title": "Acme",
                 "target_url": "https://www.linkedin.com/company/acme", "payload": {}}]}
        if path == "/automation/inbox":
            return self.proposed
        if path == "/automation/status":
            return {"state": {"mode": self.mode}}
        if path.startswith("/automation/bot/notifications?"):
            return {"items": self.notes}
        if path == "/automation/bot/notifications/ack":
            self.acked += body["ids"]
            return {"acked": len(body["ids"])}
        if path == "/automation/bot/comment-link":
            return {"ok": True, "action_id": 31, "text": "Concordo: Monte Carlo ajuda.", "author": "Ana", "read_from": "página pública", "mode": "off"}
        if path.startswith("/automation/email/gmail-query"):
            return {"query": "newer_than:%sd x" % path.split("=")[-1]}
        if path == "/automation/email/ingest":
            # o CareerOps manda arquivar m0 e m26 (confirmação/recusa); m1 seria entrevista e fica
            return {"read": len(body["messages"]), "recorded": 1,
                    "archive": [m["message_id"] for m in body["messages"] if m["message_id"] in ("<m0>", "<m26>")]}
        if path == "/automation/email/archived":
            self.archived += body["message_ids"]
            return {"marked": len(body["message_ids"])}
        if path == "/automation/saved-import/run":
            return {"id": 77, "status": "queued", "run_now": True, "mode": self.mode}
        if raw:
            return b"%PDF-1.4"
        return {}


api = FakeApi()
carreira._api = api

# 1. ids em qualquer forma
assert carreira._ids("aprovar #12, 15 e 12") == [12, 15]
assert carreira._ids(["#7", 8]) == [7, 8] and carreira._ids(None) == []

# 2. aprovar: por ids, por tipo, e o que já não estava esperando
out = core.run_query("carreira_aprovar", {"ids": ["12", "#99"]})
assert "✅ Aprovado: #12" in out and "#99: não está mais esperando" in out, out
out = core.run_query("carreira_aprovar", {"alvo": "vagas"})
assert "#3 (vai gerar o CV primeiro)" in out and "#4" in out, out
assert "texto editado só vale" in core.run_query("carreira_aprovar", {"ids": ["1", "2"], "texto": "x"}).lower()
api.calls.clear()
core.run_query("carreira_aprovar", {"ids": ["7"], "texto": "Meu texto final"})
assert ("POST", "/automation/actions/7/approve", {"text": "Meu texto final"}) in api.calls
assert "próximo horário" in core.run_query("carreira_aprovar", {"ids": ["7"]})
api.calls.clear()
out = core.run_query("carreira_aprovar", {"ids": ["7"], "agora": True})
assert ("POST", "/automation/actions/7/approve", {"run_now": True}) in api.calls and "executar agora" in out, out
api.mode = "off"
assert "desligada" in core.run_query("carreira_aprovar", {"ids": ["7"]})

# 2b. o que já foi feito, com link para acompanhar
out = core.run_query("carreira_feitos", {"alvo": "comentarios"})
assert "#40 · 02/11 22:15\n*Post de Ricardo Martins: Automação de currículos com IA*" in out, out
assert "💬 “Como você garantiu isso?”" in out and "🔗 https://www.linkedin.com/posts/ricardo-1" in out, out
assert "🕗 1 autorizado(s) esperando para executar (1 comentário)" in out and "🗂️ 3 esperando a sua aprovação (2 vagas, 1 comentário)" in out and "fila autorizada" in out, out
out = core.run_query("carreira_fila", {})
assert "#50 · na fila · no horário (8h–20h)" in out and "Post de Gabriel Rodrigues: Precificar" in out and "#51" not in out, out
assert "#41" not in out and "#42" not in out, out
assert "#42" in core.run_query("carreira_feitos", {}) and "Nada executado" in core.run_query("carreira_feitos", {"alvo": "vagas"})

# 2c. comandos fixos, sem passar pelo modelo (só a mensagem inteira conta)
c = carreira.comando
assert c("religar automacao") == ("carreira_religar", {}) and c("Religar automação.") == ("carreira_religar", {})
assert c("parar automação: viagem") == ("carreira_parar", {"texto": "viagem"})
assert c("aprovar 12 15") == ("carreira_aprovar", {"ids": "12 15", "agora": False})
assert c("aprova #12, 15 e 16 agora") == ("carreira_aprovar", {"ids": "#12, 15 e 16", "agora": True})
assert c("aprovar todas as vagas") == ("carreira_aprovar", {"alvo": "vagas", "agora": False})
assert c("aprovar todos os comentários já") == ("carreira_aprovar", {"alvo": "comentarios", "agora": True})
assert c("rejeitar 13") == ("carreira_rejeitar", {"ids": "13"})
assert c("quais foram as últimas postagens no LinkedIn?") == ("carreira_feitos", {"alvo": "comentarios"})
assert c("últimos comentários") == ("carreira_feitos", {"alvo": "comentarios"})
assert c("fila autorizada") == ("carreira_fila", {}) and c("para aprovar") == ("carreira_pendentes", {})
for frase in ("religar automação e me diga o que falta", "aprovar o 12 se estiver bom", "pode ser", "para", "qual o status da automação"):
    assert c(frase) is None, frase
assert c("https://lnkd.in/p/dZ7U2wpA") == ("carreira_comentar_varios", {"urls": ["https://lnkd.in/p/dZ7U2wpA"], "sugestao": ""})
assert c("comenta isso: lnkd.in/p/AbC") == ("carreira_comentar_varios", {"urls": ["https://lnkd.in/p/AbC"], "sugestao": ""})
assert c("https://lnkd.in/p/X1 concorde e cite a migração de ERP")[1]["sugestao"] == "concorde e cite a migração de ERP"
assert c("Links para postar: • https://lnkd.in/p/A • https://lnkd.in/p/B havia salvo esses links para comentar, adicione ao sistema • https://lnkd.in/p/A") == \
    ("carreira_comentar_varios", {"urls": ["https://lnkd.in/p/A", "https://lnkd.in/p/B"], "sugestao": ""})
assert c("veja https://www.linkedin.com/feed/update/urn:li:groupPost:98421-7522543424185561089/")[1]["urls"] == [
    "https://www.linkedin.com/feed/update/urn:li:groupPost:98421-7522543424185561089/"]
assert c("https://www.linkedin.com/in/fulano") is None
# 2d. resposta a um rascunho: ok, ok agora, não, texto final, ou um pedido para a IA
d = "💬 Rascunho #6493 para o post de Eric:\n\nTexto\n\n✅ Aprovar: responda “ok”"
assert c("ok", d) == ("carreira_aprovar", {"ids": "6493", "agora": False})
assert c("Ok agora!", d) == ("carreira_aprovar", {"ids": "6493", "agora": True})
assert c("não", d) == ("carreira_rejeitar", {"ids": "6493"})
assert c("texto final: Meu Texto, exato.", d) == ("carreira_aprovar", {"ids": "6493", "texto": "Meu Texto, exato."})
assert c("mais curto e cite concessões", d) == ("carreira_revisar", {"ids": "6493", "texto": "mais curto e cite concessões"})
assert c("mais curto", "💬 Revisado #12 para o post de X") == ("carreira_revisar", {"ids": "12", "texto": "mais curto"})
assert c("Revisar 6493: Mais técnico") == ("carreira_revisar", {"ids": "6493", "texto": "Mais técnico"})
assert c("mais curto", "uma mensagem qualquer do Lolo") is None
# 2e. os avisos que esperam o Paulo: tentar de novo / cancelar / confirmar, digitado ou respondendo ao aviso
assert c("tentar de novo #51") == ("carreira_tentar", {"ids": "#51"}) and c("Tenta novamente 51") == ("carreira_tentar", {"ids": "51"})
assert c("cancelar #7052 e #7053") == ("carreira_cancelar", {"ids": "#7052 e #7053"})
assert c("confirmar #51") == ("carreira_confirmar", {"ids": "#51"}) and c("enviar 51") == ("carreira_confirmar", {"ids": "51"})
assert c("pode enviar #12") == ("carreira_cv_ok", {"ids": "#12"})
precisa = "🙋 *Precisa de você* #51 · Founding AI Engineer · Alago\nA extensão não terminou a tempo\nDiga “tentar de novo #51” ou “cancelar #51”."
assert c("tentar de novo", precisa) == ("carreira_tentar", {"ids": "51"}) and c("tentar de novo #51", precisa) == ("carreira_tentar", {"ids": "#51"})
assert c("cancela", precisa) == ("carreira_cancelar", {"ids": "51"}) and c("ok", precisa) == ("carreira_tentar", {"ids": "51"})
expirou = "🙋 *Precisa de você* #51 · Alago\nSem confirmação em 30 minutos: nada foi enviado\nDiga “confirmar #51” (preenche de novo e envia, sem esperar outra vez) ou “cancelar #51”."
assert c("confirma", expirou) == ("carreira_confirmar", {"ids": "51"}) and c("sim", expirou) == ("carreira_confirmar", {"ids": "51"})
pronto = "🟢 *Pronto para enviar* #51 · Founding AI Engineer · Alago\nO formulário está preenchido e parado no botão Enviar."
assert c("ok", pronto) == ("carreira_confirmar", {"ids": "51"}) and c("não", pronto) == ("carreira_cancelar", {"ids": "51"})
assert c("pode", "📄 *CV para revisar* #8 · X") == ("carreira_cv_ok", {"ids": "8"})
assert c("aviso prévio = 30 dias", precisa) == ("carreira_responder", {"ids": "51", "texto": "aviso prévio = 30 dias"})
assert c("o que aconteceu com essa?", precisa) is None

# 2e'. resposta por reply, sem número: a mensagem respondida diz o que é
L = {"tipo": "list", "ids": [101, 102, 103]}
assert c("ok", ref=L) == ("carreira_aprovar", {"ids": "101 102 103", "agora": False})
assert c("Ok 1 e 3 agora", ref=L) == ("carreira_aprovar", {"ids": "101 103", "agora": True})
assert c("1, 3", ref=L) == ("carreira_aprovar", {"ids": "101 103", "agora": False})
assert c("ok menos 2", ref=L) == ("carreira_aprovar", {"ids": "101 103", "agora": False})
assert c("não", ref=L) == ("carreira_rejeitar", {"ids": "101 102 103"}) and c("nao 2", ref=L) == ("carreira_rejeitar", {"ids": "102"})
assert c("ok 7", ref=L) == ("carreira_fora_da_lista", {"total": 3}) and c("o que é a 2?", ref=L) is None
assert "1 a 3" in core.run_query(*c("não 9", ref=L))
R = {"tipo": "rascunho", "ids": [55]}
for sim in ("ok", "Sim", "s", "pode", "blz", "beleza!", "manda ver", "👍", "ok pode"):
    assert c(sim, ref=R) == ("carreira_aprovar", {"ids": "55", "agora": False}), sim
for nao in ("não", "nao", "Não.", "n", "negativo", "pula"):
    assert c(nao, ref=R) == ("carreira_rejeitar", {"ids": "55"}), nao
assert c("Técnico", ref=R) == ("carreira_revisar", {"ids": "55", "texto": "", "angulo": "tecnico"})
assert c("minha experiência", ref=R) == ("carreira_revisar", {"ids": "55", "texto": "", "angulo": "experiencia"})
assert c("mais curto", ref=R) == ("carreira_revisar", {"ids": "55", "texto": "mais curto"})
assert c("ok", ref={"tipo": "awaiting_confirm", "ids": [8]}) == ("carreira_confirmar", {"ids": "8"})
assert c("sim", ref={"tipo": "needs_user", "ids": [8], "error_code": "confirm_timeout"}) == ("carreira_confirmar", {"ids": "8"})
assert c("ok", ref={"tipo": "needs_user", "ids": [8], "error_code": "step_stuck"}) == ("carreira_tentar", {"ids": "8"})
assert c("não", ref={"tipo": "needs_user", "ids": [8]}) == ("carreira_cancelar", {"ids": "8"})
assert c("aviso prévio = 30 dias", ref={"tipo": "needs_user", "ids": [8]}) == ("carreira_responder", {"ids": "8", "texto": "aviso prévio = 30 dias"})
carreira.guardar_ref("ABC", L)
assert carreira.ref_de("ABC") == L and carreira.ref_de("XYZ") is None and carreira.ref_de(None) is None

# 2f. vagas salvas sob demanda
for frase in ("importar vagas salvas", "Puxa minhas vagas salvas do LinkedIn", "atualizar as vagas salvas agora", "importe as vagas salvas!"):
    assert c(frase) == ("carreira_vagas_salvas", {}), frase
assert c("vagas salvas") is None
modo_antes, api.mode = api.mode, "live"
api.calls.clear()
out = core.run_query("carreira_vagas_salvas", {})
assert ("POST", "/automation/saved-import/run", None) in api.calls and "#77" in out and "Aviso" in out, out
api.mode = "off"
assert "desligada" in core.run_query("carreira_vagas_salvas", {})
api.mode = modo_antes

api.calls.clear()
out = core.run_query("carreira_revisar", {"ids": "9", "texto": "mais curto"})
assert ("POST", "/automation/actions/9/revise", {"instruction": "mais curto"}) in api.calls and "Revisado para" in out and "Versão curta" in out, out
assert "#9" not in out and carreira.ref_pendente(out) == {"tipo": "rascunho", "ids": [9]}
api.calls.clear()
out = core.run_query(*c("elogio", ref={"tipo": "rascunho", "ids": [9]}))
assert ("POST", "/automation/actions/9/revise", {"instruction": "", "angle": "elogio"}) in api.calls and "tipo: elogio" in out, out
api.calls.clear()
out = core.run_query(*c("aprovar 7 agora"))
assert ("POST", "/automation/actions/7/approve", {"run_now": True}) in api.calls, api.calls

# 3. comentar um link
out = core.run_query("carreira_comentar", {"url": "https://www.linkedin.com/posts/ana_x-activity-1-a", "sugestao": "citar Monte Carlo"})
assert "Rascunho para o post de Ana" in out and "#31" not in out and "Concordo: Monte Carlo ajuda." in out and "“ok”" in out and "desligada" in out, out
assert carreira.ref_pendente(out) == {"tipo": "rascunho", "ids": [31]} and carreira.ref_pendente(out) is None
body = [c for c in api.calls if c[1] == "/automation/bot/comment-link"][-1][2]
assert body["suggestion"] == "citar Monte Carlo"
core.run_query("carreira_comentar", {"texto": "olha esse https://www.linkedin.com/feed/update/urn:li:activity:9/."})
assert [c for c in api.calls if c[1] == "/automation/bot/comment-link"][-1][2]["url"] == "https://www.linkedin.com/feed/update/urn:li:activity:9/"

# 4. respostas do formulário
api.calls.clear()
out = core.run_query("carreira_responder", {"ids": ["22"], "texto": "Notice period = 30 days; Visa = No"})
assert ("POST", "/automation/needs-user/22/answer", {"answers": [{"question": "Notice period", "answer": "30 days"},
                                                                 {"question": "Visa", "answer": "No"}]}) in api.calls, api.calls

# 5. avisos: entrega em ordem, para no primeiro que falhar, só marca o que saiu; cada um guarda a que se refere
enviados = []
carreira._enviar_com_id = lambda t: (enviados.append(t) or f"W{len(enviados)}") if "falha" not in t else None
docs = []
midia.enviar_documento = lambda data, nome, legenda="", mime="application/pdf": docs.append(nome) or True
api.notes = [{"id": 1, "text": "um", "data": {}}, {"id": 2, "text": "CV", "data": {"action_id": 5, "reply": "review_docs", "files": [{"name": "CV", "path": "/api/jobs/9/document.pdf?kind=resume"}]}},
             {"id": 3, "text": "falha", "data": {}}, {"id": 4, "text": "quatro", "data": {}}]
assert carreira.avisos_tick() == "carreira: 2/4 aviso(s) entregue(s)"
assert enviados == ["um", "CV"] and api.acked == [1, 2] and docs == ["CV-5.pdf"]
assert carreira.ref_de("W1") is None and carreira.ref_de("W2") == {"tipo": "review_docs", "ids": [5], "error_code": None}
assert c("ok", ref=carreira.ref_de("W2")) == ("carreira_cv_ok", {"ids": "5"}) and c("não", ref=carreira.ref_de("W2")) == ("carreira_cancelar", {"ids": "5"})

# 6. e-mail: a primeira leitura vai inteira como primeira leitura, as seguintes não
google.conectado = lambda: True
carreira._ids_gmail = lambda q: [f"m{i}" for i in range(30)]
carreira._mensagem = lambda mid: {"message_id": f"<{mid}>", "gmail_id": mid, "sender": "x", "subject": "s", "body": "b"}
gmail_mods = []
def fake_google(method, url, body=None, params=None):
    gmail_mods.append((method, url.rsplit("/", 2)[-2], body))
    if "m26" in url:
        raise RuntimeError("Google HTTP 500")
    return {}
google._api = fake_google
api.calls.clear()
assert carreira.email_tick() == "carreira-email: 30 lido(s), 2 novo(s) sobre candidaturas, 1 arquivado(s)"
assert gmail_mods[0] == ("POST", "m0", {"removeLabelIds": ["INBOX", "UNREAD"]}) and {g[1] for g in gmail_mods} == {"m0", "m26"}
assert api.archived == ["<m0>"]   # m26 falhou no Gmail: não é marcado e volta na próxima rodada
lotes = [c[2] for c in api.calls if c[1] == "/automation/email/ingest"]
assert [len(l["messages"]) for l in lotes] == [25, 5] and all(l["baseline"] for l in lotes)
assert any("days=45" in c[1] for c in api.calls)
api.calls.clear()
carreira.email_tick()
assert not [c[2] for c in api.calls if c[1] == "/automation/email/ingest"][0]["baseline"]
assert any("days=1" in c[1] for c in api.calls)

# 7. CareerOps fora do ar não derruba o Lolo
def fora(*a, **k):
    raise carreira.Erro("CareerOps fora do ar (Connection refused)")
carreira._api = fora
assert core.run_query("carreira_status", {}).startswith("⚠️ CareerOps fora do ar")
assert carreira.avisos_tick().startswith("carreira: CareerOps fora do ar")

print("OK — carreira")
