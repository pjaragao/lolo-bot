"""Testes offline da leitura de documentos (sem chamar o AGY). Rodar no container:
   docker exec -e HERMES_HOME=/tmp/lolotest lolo-bot /opt/hermes/.venv/bin/python /opt/joy/../tests/test_documentos.py
   (ou, no host: HERMES_HOME=/tmp/lolotest JOY_DIR=/home/paulojr/lolo-bot/joy python3 -I tests/test_documentos.py)
"""
import io
import json
import os
import shutil
import sys
import time
import zipfile

assert os.environ.get("HERMES_HOME", "").startswith("/tmp"), "use HERMES_HOME=/tmp/... (nunca o real)"
shutil.rmtree(os.environ["HERMES_HOME"], ignore_errors=True)
os.makedirs(os.environ["HERMES_HOME"])
os.environ.pop("AGY_SHIM_TOKEN", None)          # teste offline: PDF/imagem não podem chamar o AGY
sys.path.insert(0, os.environ.get("JOY_DIR", "/opt/joy"))

import arquivos, documentos  # noqa: E402

TMP = os.environ["HERMES_HOME"]


def zip_bytes(files):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, c in files.items():
            z.writestr(n, c)
    return b.getvalue()


def grava(nome, dados):
    p = os.path.join(TMP, nome)
    with open(p, "wb") as f:
        f.write(dados)
    return p


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
docx = zip_bytes({"word/document.xml": f'<w:document {W}><w:body><w:p><w:r><w:t>Contrato de locação</w:t></w:r></w:p>'
                  '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Nome</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Paulo</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
                  '<w:sdt><w:sdtContent><w:p><w:r><w:t>Dentro do controle</w:t></w:r><w:tab/><w:r><w:t>fim</w:t></w:r></w:p></w:sdtContent></w:sdt>'
                  '</w:body></w:document>'})
t, aviso = documentos.extrair(grava("a.docx", docx))
assert not aviso and "Contrato de locação" in t and "Nome | Paulo" in t and "Dentro do controle\tfim" in t, (t, aviso)

# o tipo vem do conteúdo, não da extensão (o WhatsApp nem sempre manda a extensão)
t, _ = documentos.extrair(grava("sem_extensao", docx))
assert "Contrato de locação" in t

M = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
xlsx = zip_bytes({
    "xl/workbook.xml": f'<workbook {M}><sheets><sheet name="Gastos" sheetId="1" r:id="rId1"/></sheets></workbook>',
    "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                  '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
    "xl/sharedStrings.xml": f'<sst {M}><si><t>Item</t></si><si><t>Letreiro</t></si></sst>',
    "xl/styles.xml": f'<styleSheet {M}><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>',
    "xl/worksheets/sheet1.xml": f'<worksheet {M}><sheetData>'
                                '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="inlineStr"><is><t>Data</t></is></c></row>'
                                '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2"><v>1500.0</v></c><c r="C2" s="1"><v>46023</v></c></row>'
                                '</sheetData></worksheet>'})
t, aviso = documentos.extrair(grava("g.xlsx", xlsx))
assert not aviso and "=== Gastos ===" in t and "Item |  | Data" in t and "Letreiro | 1500 | 01/01/2026" in t, (t, aviso)

A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
pptx = zip_bytes({"ppt/slides/slide2.xml": f'<p {A}><a:p><a:r><a:t>Segundo</a:t></a:r></a:p></p>',
                  "ppt/slides/slide1.xml": f'<p {A}><a:p><a:r><a:t>Primeiro</a:t></a:r></a:p></p>',
                  "ppt/notesSlides/notesSlide1.xml": f'<n {A}><a:p><a:r><a:t>fale devagar</a:t></a:r></a:p></n>'})
t, _ = documentos.extrair(grava("s.pptx", pptx))
assert t.index("Primeiro") < t.index("Segundo") and "[notas do apresentador] fale devagar" in t, t

odt = zip_bytes({"mimetype": "application/vnd.oasis.opendocument.text",
                 "content.xml": '<d xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
                                'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"><text:p>Olá<text:s text:c="2"/>mundo</text:p>'
                                '<table:table table:name="T"><table:table-row><table:table-cell><text:p>A</text:p></table:table-cell>'
                                '<table:table-cell><text:p>B</text:p></table:table-cell></table:table-row></table:table></d>'})
t, _ = documentos.extrair(grava("o.odt", odt))
assert "Olá  mundo" in t and "A | B" in t, t

t, _ = documentos.extrair(grava("r.rtf", rb"{\rtf1\ansi{\fonttbl{\f0 Arial;}}\f0 Ol\'e1 \b mundo\b0\par Segunda linha}"))
assert "Olá mundo" in t and "Segunda linha" in t and "Arial" not in t, t

t, _ = documentos.extrair(grava("p.html", "<html><head><title>x</title><style>a{}</style></head><body><p>Oi</p><script>1</script><p>Tchau</p></body></html>".encode()))
assert t.split() == ["Oi", "Tchau"], t

t, _ = documentos.extrair(grava("n.csv", "nome;valor\nCafé;3,50\n".encode("cp1252")))
assert "Café;3,50" in t, t

# formatos que não dá para ler devolvem aviso claro, nunca exceção
t, aviso = documentos.extrair(grava("velho.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 50))
assert not t and "docx" in aviso, aviso
t, aviso = documentos.extrair(grava("quebrado.docx", b"PK\x03\x04lixo"))
assert not t and aviso, aviso
t, aviso = documentos.extrair(grava("scan.pdf", b"%PDF-1.4\n%fake"))      # sem AGY_SHIM_TOKEN
assert not t and "não consegui ler" in aviso, aviso

# cache no sidecar + busca por nome/remetente + paginação
d = os.path.join(TMP, "midia")
assert arquivos.DIR == d, arquivos.DIR
agora = time.time()
p1 = arquivos.save_inbox(docx, "Certidão_de_Nascimento.docx", mime="", sender="Paulo", ts=agora - 100, kind="document")
p2 = arquivos.save_inbox(xlsx, "gastos_loja.xlsx", mime="", sender="Luisa", ts=agora - 50, caption="planilha da obra", kind="document")
p3 = arquivos.save_inbox(b"audio", "audio-1.ogg", mime="audio/ogg", sender="Paulo", ts=agora, kind="audio", extra={"texto": "compra de tinta"})
assert documentos.achar("certidão nascimento")[0]["path"] == p1
assert documentos.achar("planilha obra")[0]["path"] == p2
assert documentos.achar("")[0]["path"] == p2                    # sem busca: documento mais recente (áudio fica depois)
assert documentos.achar("tinta")[0]["path"] == p3               # acha pelo texto já transcrito
out = documentos.ler("certidao")
assert "Contrato de locação" in out and "dado externo" in out, out
assert json.load(open(p1 + ".json", encoding="utf-8"))["texto"].startswith("Contrato"), "texto não foi guardado"
os.remove(p1)
assert "Contrato de locação" not in documentos.ler("certidao")  # arquivo sumiu: não devolve o cache de outro
assert "Nenhum arquivo" in documentos.ler("xyzxyz")
longo = arquivos.save_inbox(("linha\n" * 5000).encode(), "longo.txt", sender="P", ts=agora - 10, kind="document")
pg1 = documentos.ler("longo", max_chars=100)
assert "offset=100" in pg1 and "faltam" in pg1, pg1[-120:]
assert documentos.ler("longo", offset=29950).count("linha") >= 1 and "faltam" not in documentos.ler("longo", offset=29950)
bloco = documentos.bloco_para_chat(longo, max_chars=50)
assert bloco.startswith("[conteúdo do documento «longo.txt»") and "documento_ler" in bloco, bloco
assert "Certidão" not in documentos.listar() and "gastos_loja.xlsx" in documentos.listar()

print("OK — documentos")
