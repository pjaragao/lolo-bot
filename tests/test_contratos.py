"""Testes offline dos contratos e das listas do Google Tasks (sem Google: tudo cai no .docx local / fila local). Rodar:
   docker exec -e HERMES_HOME=/tmp/lolotest lolo-bot /opt/hermes/.venv/bin/python /opt/joy/../tests/test_contratos.py
   (ou, no host: HERMES_HOME=/tmp/lolotest JOY_DIR=/home/paulojr/lolo-bot/joy python3 -I tests/test_contratos.py)
"""
import io
import os
import re
import shutil
import sys
import xml.dom.minidom
import zipfile

assert os.environ.get("HERMES_HOME", "").startswith("/tmp"), "use HERMES_HOME=/tmp/... (nunca o real)"
shutil.rmtree(os.environ["HERMES_HOME"], ignore_errors=True)
os.makedirs(os.environ["HERMES_HOME"])
for k in ("EVOLUTION_API_URL", "EVOLUTION_API_KEY", "AGY_SHIM_TOKEN"):
    os.environ.pop(k, None)                      # nada sai para a rede
sys.path.insert(0, os.environ.get("JOY_DIR", "/opt/joy"))

import contratos as C  # noqa: E402
import core  # noqa: E402
import google  # noqa: E402

assert not google.conectado()

# 1. extenso, valores, percentuais e datas
assert C.extenso(1234) == "mil duzentos e trinta e quatro"
assert C.extenso(1100) == "mil e cem" and C.extenso(100) == "cem" and C.extenso(101) == "cento e um"
assert C.extenso(1_500_000) == "um milhão e quinhentos mil"
assert C.extenso(2_340_000) == "dois milhões trezentos e quarenta mil"
assert C.reais_extenso(50000) == "cinquenta mil reais"
assert C.reais_extenso(1) == "um real"
assert C.reais_extenso(1234.56) == "mil duzentos e trinta e quatro reais e cinquenta e seis centavos"
assert C.reais_extenso(1_000_000) == "um milhão de reais"
assert C.brl(1234567.8) == "R$ 1.234.567,80"
assert C.pct_extenso(10) == "dez por cento" and C.pct_extenso(2.5) == "dois vírgula cinco por cento"
assert C._num("R$ 50.000,00") == 50000 and C._num("50 mil") == 50000 and C._num("1,5 milhão") == 1_500_000
assert C._num("50.000") == 50000 and C._num("10%") == 10 and C._num("") is None
assert C.data_extenso("2026-11-01") == "1º de novembro de 2026" and C.data_extenso("29/10/2026") == "29 de outubro de 2026"
assert C.ordinal(1) == "PRIMEIRA" and C.ordinal(21) == "VIGÉSIMA PRIMEIRA" and C.ordinal(2, masc=True) == "SEGUNDO"

# 2. CPF / CNPJ (inclui o exemplo de CNPJ alfanumérico da Receita)
assert C.cpf_valido("529.982.247-25") and not C.cpf_valido("529.982.247-24") and not C.cpf_valido("111.111.111-11")
assert C.cnpj_valido("11.222.333/0001-81") and not C.cnpj_valido("11.222.333/0001-80")
assert C.cnpj_valido("12.ABC.345/01DE-35") and not C.cnpj_valido("12.ABC.345/01DE-34")
assert C.fmt_doc("11222333000181") == "11.222.333/0001-81" and C.fmt_doc("52998224725") == "529.982.247-25"

PJ1 = {"nome": "Alfa Engenharia Ltda.", "nome_curto": "Alfa", "documento": "11.222.333/0001-81",
       "endereco": "Rua A, 1, Centro, Florianópolis/SC", "email": "user@example.com",
       "representante": {"nome": "Ana Souza", "cargo": "Diretora", "cpf": "529.982.247-25"}}
PJ2 = {"nome": "Beta Consultoria Ltda.", "nome_curto": "Beta", "documento": "12.ABC.345/01DE-35",
       "endereco": "Rua B, 2, Centro, Florianópolis/SC", "email": "user@example.com",
       "representante": {"nome": "Bruno Lima", "cargo": "Sócio", "cpf": "111.444.777-35"}}
BASE = {"tipo": "servicos", "partes": {"contratante": PJ1, "contratada": PJ2}, "objeto": "consultoria financeira",
        "valor": 50000, "parcelas": [{"descricao": "Entrada", "percentual": 10, "quando": "na assinatura"},
                                     {"descricao": "Final", "percentual": 90, "quando": "na entrega final"}],
        "foro": "Florianópolis/SC", "data": "2026-10-29", "codigo": "PJ99999",
        "lgpd": {"encarregados": {"contratante": "user@example.com", "contratada": "user@example.com"}}}


def texto(m):
    return "\n".join(" ".join(str(x) if not isinstance(x, list) else " ".join(map(str, x)) for x in b[1:]) for b in m["blocos"])


def doc_xml(m):
    z = zipfile.ZipFile(io.BytesIO(C.docx_de(m)))
    for n in z.namelist():
        xml.dom.minidom.parseString(z.read(n))          # todo XML do pacote é válido
    return z.read("word/document.xml").decode(), z.read("word/footer1.xml").decode()


# 3. simples x completo
s = C.montar({**BASE, "nivel": "simples"})
ts = texto(s)
assert "DA PROTEÇÃO DE DADOS PESSOAIS" in ts and "DO ATRASO NO PAGAMENTO" in ts and "DA ASSINATURA ELETRÔNICA" in ts
assert "DA PROPRIEDADE INTELECTUAL" not in ts and "ANTICORRUPÇÃO" not in ts and "REFORMA TRIBUTÁRIA" not in ts
assert "R$ 5.000,00 (cinco mil reais)" in ts and "R$ 45.000,00 (quarenta e cinco mil reais)" in ts
assert "CLÁUSULA PRIMEIRA – DO OBJETO" in ts and "1.1." in ts
assert not s["ctx"].pend, s["ctx"].pend                 # dados completos: nada de [●]
docxml, rodape = doc_xml(s)
assert C.PEND not in docxml and "PAGE" in rodape and "NUMPAGES" in rodape and 'w:val="both"' in C._estilos(11)

cpl = C.montar({**BASE, "nivel": "completo"})
tc = texto(cpl)
for t in ("DA PROPRIEDADE INTELECTUAL", "DA CONDUTA ÉTICA E ANTICORRUPÇÃO", "REFORMA TRIBUTÁRIA", "DAS PENALIDADES",
          "DA RESPONSABILIDADE", "DOS TRIBUTOS", "Resolução CD/ANPD nº 15/2024", "user@example.com", "421-A"):
    assert t in tc, t
assert len(cpl["clausulas"]) > len(s["clausulas"]) + 8
assert "não passou na validação" not in " ".join(cpl["ctx"].avisos)

# módulos extras / removidos e cláusula personalizada
m = C.montar({**BASE, "nivel": "simples", "modulos": ["multa", "nao_aliciamento"], "sem_modulos": ["autonomia"],
              "clausulas_extras": [{"titulo": "Do sigilo bancário", "itens": ["Item extra um.", "Item extra dois."]}]})
tm = texto(m)
assert "DAS PENALIDADES" in tm and "DA NÃO CONTRATAÇÃO DE PROFISSIONAIS" in tm and "VÍNCULO EMPREGATÍCIO" not in tm
assert "DO SIGILO BANCÁRIO" in tm and "Item extra dois." in tm

# 4. pendências e avisos
m = C.montar({**BASE, "partes": {"contratante": {**PJ1, "email": ""}, "contratada": {**PJ2, "documento": "11.222.333/0001-80"}},
              "parcelas": [{"percentual": 10, "quando": "x"}, {"percentual": 80, "quando": "y"}]})
assert "e-mail da CONTRATANTE" in m["ctx"].pend
assert any("validação" in a for a in m["ctx"].avisos) and any("somam 90%" in a for a in m["ctx"].avisos)
assert C.PEND in doc_xml(m)[0] and "highlight" in doc_xml(m)[0]
assert "Faltando" in C.previa({**BASE, "partes": {"contratante": {**PJ1, "email": ""}, "contratada": PJ2}})

# 5. relação de consumo e pessoa física
pf = {"nome": "Carla Dias", "documento": "529.982.247-25", "endereco": "Rua C, 3, Florianópolis/SC", "genero": "f",
      "email": "user@example.com"}
m = C.montar({**BASE, "nivel": "completo", "consumidor": True, "fora_estabelecimento": True, "multa_mora_percentual": 10,
              "modulos": ["arbitragem"], "partes": {"contratante": pf, "contratada": PJ2}})
tm = texto(m)
assert "DOS DIREITOS DO CONSUMIDOR" in tm and "art. 49 do CDC" in tm and "DA RESPONSABILIDADE" not in tm
assert "DA ARBITRAGEM" not in tm and "multa moratória de 2% (dois por cento)" in tm and "a CONTRATANTE" in tm
assert "art. 101, I, do CDC" in tm and "<w:sz w:val=\"24\"/>" in C._estilos(12)
pf_m = {"nome": "Diego Rocha", "documento": "529.982.247-25", "endereco": "Rua D, 4, São José/SC", "email": "user@example.com"}
m = C.montar({**BASE, "partes": {"contratante": PJ1, "contratada": pf_m}})
tm = texto(m)
assert "doravante denominado **CONTRATADO**" in tm and "residente e domiciliado" in tm and "442-B" in tm
assert any("sem gênero" in a for a in m["ctx"].avisos)

# 6. LGPD como operador → anexo de tratamento de dados
m = C.montar({**BASE, "nivel": "completo", "escopo": ["Modelo financeiro", "Relatório final"],
              "lgpd": {"papel": "operador", "dados": "nome e CPF de clientes", "titulares": "clientes"}})
tm = texto(m)
assert "atuando como operadora" in tm and "ANEXO I – ESCOPO" in tm and "ANEXO II – TRATAMENTO DE DADOS PESSOAIS" in tm
assert "Anexo I" in tm and "Medidas mínimas de segurança" in tm

# 7. todos os tipos montam
for extra in (
    {"tipo": "nda", "finalidade": "avaliar uma parceria", "valor_referencia": 100000},
    {"tipo": "nda", "mutuo": False, "finalidade": "avaliar uma parceria"},
    {"tipo": "fornecimento", "produtos": "peças de moda fitness", "local_entrega": "loja da compradora",
     "produtos_lista": ["Legging — R$ 120,00"]},
    {"tipo": "consignacao", "produtos": "peças de moda fitness", "comissao_percentual": 35},
    {"tipo": "influenciador", "marca": "SIÉ Wear", "plataformas": "Instagram @perfil", "entregas": ["2 reels", "4 stories"],
     "modulos": ["infl_exclusividade"], "exclusividade": {"meses": 3, "segmento": "moda fitness"}},
    {"tipo": "aditivo", "contrato_original": {"titulo": "Contrato de Prestação de Serviços", "data": "2026-10-29"},
     "alteracoes": ["A cláusula 2.3 passa a vigorar com prazo de 30 (trinta) dias."]},
    {"tipo": "distrato", "contrato_original": {"titulo": "Contrato de Prestação de Serviços", "data": "2026-10-29"},
     "acerto": {"valor": 5000, "pagador": "p1"}},
):
    m = C.montar({**BASE, "nivel": "completo", **extra})
    tm = texto(m)
    assert "CLÁUSULA PRIMEIRA" in tm and "DO FORO" in tm or extra["tipo"] in ("aditivo", "distrato"), extra["tipo"]
    doc_xml(m)
assert "ACORDO DE CONFIDENCIALIDADE MÚTUO" in texto(C.montar({**BASE, "tipo": "nda", "finalidade": "x"}))
assert "PARTE RECEPTORA" in texto(C.montar({**BASE, "tipo": "nda", "mutuo": False, "finalidade": "x"}))
t_ad = texto(C.montar({**BASE, "tipo": "aditivo", "contrato_original": {"titulo": "Contrato X", "data": "2026-10-29"},
                       "alteracoes": ["Nova redação."]}))
assert "PRIMEIRO TERMO ADITIVO AO CONTRATO X" in t_ad and "DA RATIFICAÇÃO" in t_ad and "29 de outubro de 2026" in t_ad
t_di = texto(C.montar({**BASE, "tipo": "distrato", "contrato_original": {"titulo": "Contrato X"}, "acerto": {"valor": 5000}}))
assert "R$ 5.000,00 (cinco mil reais)" in t_di and "quitação" in t_di and "art. 472" in t_di
try:
    C.montar({**BASE, "tipo": "locacao"})
    raise AssertionError("tipo inválido deveria falhar")
except ValueError as exc:
    assert "não existe" in str(exc)

# 8. gerar sem Google → .docx local + registro; editar = nova versão; aditivo a partir do registro
r = C.gerar({**BASE, "nivel": "simples"})
cid = re.search(r"\((CT-\d{8}-\d{2})\)", r).group(1)
assert os.path.isfile(os.path.join(C.DIR, f"{cid}_v1.docx")), r
assert cid in C.listar() and oct(os.stat(C._reg_path(cid)).st_mode)[-3:] == "600"
r2 = C.editar(cid, {"prazo_pagamento_dias": 30})
assert os.path.isfile(os.path.join(C.DIR, f"{cid}_v2.docx")), r2
reg = C.carregar(cid)
assert len(reg["versoes"]) == 2 and reg["dados"]["prazo_pagamento_dias"] == 30 and reg["dados"]["objeto"] == BASE["objeto"]
m = C.montar({"tipo": "aditivo", "base_id": cid, "alteracoes": ["Texto novo."]})
assert "Alfa" in m["nome_arquivo"] and "TERMO ADITIVO AO CONTRATO DE PRESTAÇÃO DE SERVIÇOS" in m["titulo"]
assert "o Contrato de Prestação de Serviços (“Contrato”)" in texto(m)
assert "contrato_gerar" in core.run_query("contrato_modelos", {}) or "Contratos" in core.run_query("contrato_modelos", {})
assert "CT-" in core.run_query("contrato_listar", {})
assert "Prévia" in core.run_query("contrato_previa", {"dados": {**BASE, "nivel": "simples"}})
assert C._mesclar({"a": {"b": 1, "c": 2}, "d": 1}, {"a": {"b": 9}, "d": None}) == {"a": {"b": 9, "c": 2}}

# 9. revisão de contrato recebido
rev = C.revisar("CONTRATO. Cláusula 1 – Do objeto: serviços. O pagamento será de R$ 10.000,00. Em caso de descumprimento, "
                "multa de 150% do valor. O valor será reajustado mensalmente pelo IGP-M. Fica eleito o foro da comarca de "
                "Manaus/AM. " + "Texto. " * 60)
assert "Proteção de dados (LGPD)" in rev.split("Não encontrei")[1] and "CC, art. 412" in rev and "10.192" in rev
assert "Manaus" in rev and "título executivo" in rev

# 10. Google Tasks com listas (offline: fila local guarda a lista)
t1 = google.criar_tarefa("Revisar skill de contratos", lista="Melhorias Lolo")
t2 = google.criar_tarefa("Comprar pão")
assert t1["pendente"] and t1["lista"] == "Melhorias Lolo"
padrao = [t["titulo"] for t in google.listar_tarefas()]
assert "Comprar pão" in padrao and "Revisar skill de contratos" not in padrao
assert [t["titulo"] for t in google.listar_tarefas(lista="Melhorias Lolo")] == ["Revisar skill de contratos"]
assert len(google.listar_tarefas(lista="todas")) == 2
assert "Melhorias Lolo" in core.run_query("tarefa_listar", {"lista": "Melhorias Lolo"})
assert "não conectado" in core.run_query("listas_listar", {})
assert "Informe id" in core.run_query("tarefa_mover", {"lista_destino": "x"}) or "não conectado" in core.run_query("tarefa_mover", {"lista_destino": "x"})
assert google._sem_acento("Ação") == "acao" and google._tasks_url("abc") .endswith("/lists/abc/tasks")

# 11. formatar contrato já redigido (texto mantido) e recusa de gerar sem dados
TXT = ("INSTRUMENTO PARTICULAR DE PRESTAÇÃO DE SERVIÇOS\n\nCONTRATANTE:\nAlfa Ltda., CNPJ 11.222.333/0001-81.\n\n"
       "CLÁUSULA PRIMEIRA – DO OBJETO\n1.1. Serviços de consultoria financeira para a CONTRATANTE.\n"
       "CLÁUSULA SEGUNDA – DO PREÇO\n2.1. Valor de R$ 10.000,00, assim:\na) Entrada: 10%;\nb) Final: 90%.\n\n"
       "Florianópolis/SC, 29 de outubro de 2026.\n\n__________\nCONTRATANTE: Alfa\nAna Souza\nCPF: 529.982.247-25\n\n"
       "__________\nCONTRATADA: Beta\nBruno Lima\n")
assert C.parece_contrato(TXT) and not C.parece_contrato("lista de compras")
tit, B = C.blocos_de_texto(TXT)
kinds = [b[0] for b in B]
assert tit.startswith("INSTRUMENTO") and kinds.count("h") == 2 and "alineas_txt" in kinds and "centro" in kinds
ass = [b for b in B if b[0] == "assinaturas"][0][1]
assert len(ass) == 2 and ass[0][-1] == "CPF: 529.982.247-25" and ass[1][0] == "**CONTRATADA: Beta**"
assert "Serviços de consultoria financeira para a CONTRATANTE." in str(B)          # texto intacto
zipfile.ZipFile(io.BytesIO(C.render_docx(B, "x", tit)))
assert "Não gerei" in C.gerar({}) and "Não gerei" in core.run_query("contrato_gerar", {}) and "Não gerei" in C.previa({})

print("OK — contratos + listas do Tasks")
