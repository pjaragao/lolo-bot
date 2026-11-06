"""Testes unitários offline do lolo-bot (recorrência, lembretes, datas relativas, sistemas, classificação)."""
import datetime
import os
import shutil
import sys

assert os.environ.get("HERMES_HOME", "").startswith("/tmp"), "use HERMES_HOME=/tmp/... (nunca o real)"
shutil.rmtree(os.environ["HERMES_HOME"], ignore_errors=True)
os.makedirs(os.environ["HERMES_HOME"])
sys.path.insert(0, os.environ.get("JOY_DIR", "/opt/joy"))

import core  # noqa: E402
import google  # noqa: E402
import lembretes  # noqa: E402
import pessoas  # noqa: E402
import sistemas  # noqa: E402

# 1. Teste de build_rrule (recorrências do Google Calendar)
ini = google.parse_dt("2026-10-30T14:00")  # sexta-feira
assert google.build_rrule("semanal", ini) == ["RRULE:FREQ=WEEKLY;BYDAY=FR"]
assert google.build_rrule("semanal", ini, dias_semana="seg,qua,sex") == ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"]
assert google.build_rrule("diario", ini) == ["RRULE:FREQ=DAILY"]
assert google.build_rrule("dias uteis", ini) == ["RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"]
assert google.build_rrule("mensal", ini) == ["RRULE:FREQ=MONTHLY;BYMONTHDAY=30"]
assert google.build_rrule("anual", ini) == ["RRULE:FREQ=YEARLY"]
r_until = google.build_rrule("semanal", ini, ate="2026-12-31")
assert r_until and "UNTIL=20270101T025959Z" in r_until[0], r_until

# 2. Teste de datas relativas (_rel)
hoje = datetime.date.today()
assert core._rel("hoje 15:00") == f"{hoje.isoformat()}T15:00"
assert core._rel("amanhã 09:30") == f"{(hoje + datetime.timedelta(days=1)).isoformat()}T09:30"
nome_hoje = core.DIAS_PT[hoje.weekday()]
assert core._rel(f"nesta {nome_hoje} 18:00") == f"{hoje.isoformat()}T18:00"
assert core._rel(f"próxima {nome_hoje} 18:00") == f"{(hoje + datetime.timedelta(days=7)).isoformat()}T18:00"

# 3. Teste de classificação de agendas e regra da Luisa
assert pessoas.classificar_agenda("Reunião Teams Truelogic", "") == "trabalho"
assert not pessoas.envolve_luisa("Reunião Teams Truelogic", "", None, categoria="trabalho")
assert not pessoas.deve_perguntar_luisa("trabalho", False, None)
assert pessoas.classificar_agenda("JJ Paulinho", "") == "familia"
assert pessoas.deve_perguntar_luisa("familia", False, None)
assert pessoas.classificar_agenda("Academia", "") == "pessoal"
assert pessoas.classificar_agenda("Obra loja SIÉ", "") == "sie"

# 4. Teste de lembretes (criar, editar, listar, cancelar e conteúdo=tarefas)
c1 = lembretes.criar("Tomar creatina", "08:00", "diario")
assert "Lembrete #1 criado" in c1, c1
e1 = lembretes.editar(1, texto="Tomar creatina e whey", hora="08:30")
assert "atualizado" in e1 and "08:30" in e1 and "whey" in e1, e1
assert "08:30" in lembretes.listar()
t1 = google.criar_tarefa("Comprar ração", notas="15kg", data=hoje.isoformat())
msg_tar = lembretes._mensagem({"conteudo": "tarefas", "texto": ""})
assert "Comprar ração" in msg_tar, msg_tar
e_tar = google.editar_tarefa(t1["id"], notas="20kg")
assert e_tar["notas"] == "20kg", e_tar
assert google.concluir_tarefa(busca="Comprar ração") == "ok"
assert "cancelado" in lembretes.cancelar(1)

# 5. Teste de proteção de escrita do SISTEMAS.md
with open(sistemas.ARQ, "w", encoding="utf-8") as fh:
    fh.write("# Mapa\n\n## 10. Backlog de ideias\n<!-- IDEIAS-INICIO -->\n<!-- IDEIAS-FIM -->\n")
res_id = sistemas.ideia_salvar("Teste Ideia", "https://example.com", "Resumo X", "Sugestão Y", "lolo-bot", "P")
assert "Ideia salva" in res_id
assert "Teste Ideia" in sistemas.ideias_listar()

print("OK — lolo_core")
