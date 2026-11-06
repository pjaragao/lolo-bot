"""Testes offline da organização de arquivos (Drive simulado em memória). Reproduz o incidente de 29/10: o Paulo manda o
contrato assinado e pede para arquivar → o Lolo tem de subir o PDF original, sem gerar/formatar outro, e nunca duplicar Docs.
   HERMES_HOME=/tmp/lolotest JOY_DIR=/home/paulojr/lolo-bot/joy python3 -I tests/test_arquivos.py
"""
import hashlib
import json
import os
import shutil
import sys
import time

assert os.environ.get("HERMES_HOME", "").startswith("/tmp"), "use HERMES_HOME=/tmp/... (nunca o real)"
shutil.rmtree(os.environ["HERMES_HOME"], ignore_errors=True)
os.makedirs(os.environ["HERMES_HOME"])
os.environ.pop("AGY_SHIM_TOKEN", None)
sys.path.insert(0, os.environ.get("JOY_DIR", "/opt/joy"))

import arquivos  # noqa: E402
import contratos  # noqa: E402
import core  # noqa: E402
import documentos  # noqa: E402
import drive  # noqa: E402
import google  # noqa: E402
import midia  # noqa: E402

DOC = drive.GDOC + "document"


# --------------------------------------------------------------------------- Drive falso
class FakeDrive:
    def __init__(self):
        self.files, self.n = {}, 0

    def novo(self, nome, mime, pasta, dados=b"", props=None):
        self.n += 1
        fid = f"f{self.n}"
        self.files[fid] = {"id": fid, "nome": nome, "mime": mime, "pasta": pasta, "dados": dados, "props": props or {},
                           "lixeira": False, "versoes": 1}
        return self._fmt(fid)

    def _fmt(self, fid):
        f = self.files[fid]
        return {"id": fid, "nome": f["nome"], "tipo": f["mime"].split("/")[-1], "mime": f["mime"], "modificado": "2026-10-29",
                "link": f"https://drive/{fid}", "md5": hashlib.md5(f["dados"]).hexdigest() if f["mime"] != DOC else None}

    def vivos(self, pasta=None):
        return [f for f in self.files.values() if not f["lixeira"] and (pasta is None or f["pasta"] == pasta)]


FD = FakeDrive()


def _texto_doc(docx: bytes) -> bytes:
    """O que o Drive faz ao converter: o Doc passa a ter o texto do .docx."""
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(docx)) as z:
        return documentos._docx(z).encode()
drive.enviar_arquivo = lambda nome, dados, mime, pasta="root", converter_para=None, props=None: \
    FD.novo(nome, converter_para or mime, pasta, _texto_doc(dados) if converter_para else dados, props)
drive.no_lugar = lambda pasta, n=100: [FD._fmt(f["id"]) for f in FD.vivos(pasta)]
drive.metadados = lambda fid: {**FD._fmt(fid), "parents": [FD.files[fid]["pasta"]], "lixeira": FD.files[fid]["lixeira"]}
drive._download = lambda fid, mime=None: FD.files[fid]["dados"]
drive.exportar = lambda fid, mime: b"%PDF-1.4 /Type /Page " + fid.encode()
drive.ler = lambda fid, max_chars=8000: {**FD._fmt(fid), "texto": FD.files[fid]["dados"].decode("utf-8", "replace"), "lido": True}


def _atualizar(fid, dados, mime):
    FD.files[fid]["dados"] = dados if FD.files[fid]["mime"] != DOC else _texto_doc(dados)
    FD.files[fid]["versoes"] += 1
    return FD._fmt(fid)


drive.atualizar_arquivo = _atualizar
drive.renomear = lambda fid, nome: FD.files[fid].update(nome=nome) or FD._fmt(fid)
drive.pdf_de = lambda doc_id: next((FD._fmt(f["id"]) for f in FD.vivos() if f["props"].get("lolo_pdf_de") == doc_id), None)
drive.criar_doc = lambda titulo, conteudo="", pasta="root": FD.novo(titulo, DOC, pasta, conteudo.encode())
google.conectado = lambda: True
midia.enviar_documento = lambda *a, **k: True

PASTA = "pastaPJ26004"
FD.files[PASTA] = {"id": PASTA, "nome": "PJ26004 - Concessao Navegantes - SA Paulista", "mime": drive.GDOC + "folder",
                   "pasta": "root", "dados": b"", "props": {}, "lixeira": False, "versoes": 1}
contratos._pasta_do_codigo = lambda codigo: PASTA if codigo == "PJ26004" else None

TEXTO = ("INSTRUMENTO PARTICULAR DE PRESTAÇÃO DE SERVIÇOS TÉCNICOS ESPECIALIZADOS\n\nCONTRATANTE: RACA SERVIÇOS AMBIENTAIS "
         "LTDA., CNPJ 14.596.598/0001-38.\nCONTRATADA: CLC - CONSULTORES ASSOCIADOS LTDA., CNPJ 25.102.745/0001-92.\n\n"
         "CLÁUSULA PRIMEIRA – DO OBJETO\n1.1. Modelagem financeira para infraestrutura.\n\nCLÁUSULA SEGUNDA – DO PREÇO\n"
         "2.1. R$ 50.000,00.\n2.3. Pagamento em 15 dias.\n\nCLÁUSULA QUINTA – DO FORO\n5.1. Florianópolis/SC.\n")

# 1. nome-base reconhece o mesmo documento com sufixos diferentes
assert drive.nome_base("Contrato de Prestação de Serviços - RACA e CLC (Formatado)") == \
       drive.nome_base("Contrato Prestação de Serviços - RACA e CLC (Versão Final Formatada)") == \
       drive.nome_base("Contrato de Prestação de Serviços - RACA e CLC (Assinado) (formatado).pdf")
assert drive.nome_base("Contrato RACA e CLC") != drive.nome_base("Contrato RACA e SA Paulista")
assert arquivos.nome_legivel("Contrato de PrestaÃ§Ã£o de ServiÃ§os") == "Contrato de Prestação de Serviços"

# 2. já existe a minuta formatada na pasta (Doc do Paulo)
minuta = FD.novo("Contrato de Prestação de Serviços - RACA e CLC (Formatado)", DOC, PASTA, TEXTO.encode())

# 3. doc_criar com o mesmo contrato → não cria outro; edita o MESMO Doc (nome igual) ou recusa (só texto parecido)
antes = len(FD.vivos(PASTA))
r = core.run_query("doc_criar", {"titulo": "Contrato Prestação de Serviços - RACA e CLC (Versão Final Formatada)",
                                 "corpo": TEXTO, "pasta_id": PASTA})
assert "Atualizei o MESMO Doc" in r, r
assert len([f for f in FD.vivos(PASTA) if f["mime"] == DOC]) == 1, "não pode surgir um segundo Doc"
assert FD.files[minuta["id"]]["versoes"] == 2
r = core.run_query("doc_criar", {"titulo": "Minuta CLC Modelagem", "corpo": TEXTO.replace("15 dias", "20 dias"),
                                 "pasta_id": PASTA})
assert "Não criei" in r and minuta["id"] in r, r
r = core.run_query("doc_criar", {"titulo": "Notas da reunião", "corpo": "Pauta: cronograma.", "pasta_id": PASTA})
assert "Google Doc criado" in r, r                                   # documento diferente: cria normalmente
r = core.run_query("doc_criar", {"titulo": "Notas da reunião", "corpo": "Pauta: outra.", "pasta_id": PASTA})
assert "Não criei" in r, r
r = core.run_query("doc_criar", {"titulo": "Notas da reunião", "corpo": "Pauta: outra.", "pasta_id": PASTA, "forcar": True})
assert "Google Doc criado" in r, r

# 4. formatar com o id do Doc atualiza ESSE Doc e o PDF dele no lugar (2ª vez não cria outro PDF)
docs_antes = len([f for f in FD.vivos() if f["mime"] == DOC])
r1 = core.run_query("contrato_formatar", {"id": minuta["id"], "texto": TEXTO.replace("15 dias", "30 dias")})
r2 = core.run_query("contrato_formatar", {"id": minuta["id"]})
assert "MESMO Doc" in r1 and "MESMO Doc" in r2, (r1, r2)
assert len([f for f in FD.vivos() if f["mime"] == DOC]) == docs_antes
pdfs = [f for f in FD.vivos() if f["props"].get("lolo_pdf_de") == minuta["id"]]
assert len(pdfs) == 1 and pdfs[0]["versoes"] == 3, pdfs                # criado no passo 3, atualizado 2x
assert FD.files[minuta["id"]]["nome"] == "Contrato de Prestação de Serviços - RACA e CLC (Formatado)", "não renomeia à toa"

# 5. o Paulo manda o contrato ASSINADO e pede "arquive na pasta do projeto"
assinado = ("INSTRUMENTO PARTICULAR ...\n[Carimbo/Assinatura Digital]: ASSINADO DIGITALMENTE POR Paulo Jose Aragao Junior | "
            "safeID | ICP Brasil | Data: 29/10/2026 17:49\nAssinado de forma digital por a5986f45")
pdf_bytes = b"%PDF-1.7 assinado de verdade " + os.urandom(64)
p = arquivos.save_inbox(pdf_bytes, "Contrato de PrestaÃ§Ã£o de ServiÃ§os - RACA e CLC _261029_174918.pdf",
                        mime="application/pdf", sender="Paulo", kind="document", extra={"texto": assinado})
assert documentos.assinado_pendente()["path"] == p

for consulta, args in (("contrato_formatar", {"texto": TEXTO, "pasta_id": PASTA}),
                       ("contrato_gerar", {"dados": {"tipo": "servicos"}}),
                       ("contrato_editar", {"id": "CT-1", "alteracoes": {"x": 1}}),
                       ("doc_criar", {"titulo": "Contrato (Assinado)", "corpo": TEXTO, "pasta_id": PASTA})):
    r = core.run_query(consulta, args)
    assert r.startswith("⛔ Parei") and "documento_salvar" in r, (consulta, r)

n_antes = len(FD.vivos(PASTA))
r = core.run_query("documento_salvar", {"busca": "contrato", "codigo": "PJ26004"})
assert "ORIGINAL" in r, r
novos = FD.vivos(PASTA)[n_antes:]
assert len(novos) == 1 and novos[0]["dados"] == pdf_bytes, "sobe os bytes intactos"
assert novos[0]["nome"] == "Contrato de Prestação de Serviços - RACA e CLC.pdf", novos[0]["nome"]
assert documentos.assinado_pendente() is None, "depois de arquivado a trava solta"
r = core.run_query("documento_salvar", {"busca": "contrato", "pasta_id": PASTA})
assert "já estava arquivado" in r and len(FD.vivos(PASTA)) == n_antes + 1, r          # não duplica
assert "falta a pasta" in core.run_query("documento_salvar", {"busca": "contrato"})

# 6. um PDF assinado nunca é sobrescrito pelo formatar (só PDFs marcados como do Lolo)
core.run_query("contrato_formatar", {"id": minuta["id"]})
assert FD.files[novos[0]["id"]]["dados"] == pdf_bytes

# 7. lixeira só com confirmação
assert "Não mexi" in core.run_query("drive_lixeira", {"id": minuta["id"]})

print("OK — arquivos")
