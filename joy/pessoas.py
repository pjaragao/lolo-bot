"""Pessoas e regras de convite e classificação de agenda do Paulo."""
import re
from typing import Optional

LUISA_EMAIL = "user@example.com"
FILHOS = {"Otávio": ["otávio", "otavio", "tata", "tataco"], "Paulinho": ["paulinho", "pjan", "pj", "pjtinha"]}

# Classificações automáticas de agenda
_RX_SIE = re.compile(r"\b(si[ée]|si[ée][-\s]?joy|joy\s+wellness|lpo\b|loja\s+si[ée]|reembolso\s+si[ée])\b", re.I)
_RX_VIAGEM = re.compile(
    r"\b(viagem|voo|v[oô]o|aeroporto|hotel|pousada|check[-\s]?in|check[-\s]?out|embarque|passagem|"
    r"airbnb|hospedagem|transfer|aluguel de carro|f[ée]rias|feriad[ãa]o)\b", re.I)
_RX_TRABALHO = re.compile(
    r"\b(trabalho|reuni[ãa]o|teams|meet\b|zoom\b|call\b|entrevista|truelogic|vaga|prospec[çc][ãa]o|"
    r"loteamento|fornecedor|or[çc]amento|cliente|projeto|engenharia|eiv\b|bauer|viva ambiental|"
    r"navegantes|altini|alinhamento|apresenta[çc][ãa]o|proposta|contrato comercial)\b", re.I)
_RX_FAMILIA = re.compile(
    r"\b(lu[ií]sa|lu\b|esposa|mulher|casal|fam[ií]lia|filhos?|meninos|ot[áa]vio|tata|tataco|"
    r"paulinho|pjan|pj\b|pjtinha|jj\b|jiu[-\s]?jitsu|escola|reuni[ãa]o de pais|pediatra|oftalmo|"
    r"anivers[áa]rio|casamento|jantar|almo[çc]o em fam|passeio|festa)\b", re.I)

# Assuntos em que a Luisa é convidada automaticamente quando flag=None
_ENVOLVE = re.compile(
    r"\b(lu[ií]sa|lu\b|esposa|mulher|casal|fam[ií]lia|filhos?|meninos|ot[áa]vio|tata|tataco|"
    r"paulinho|pjan|pj\b|pjtinha|jantar|almo[çc]o em fam|anivers[áa]rio|casamento|escola|"
    r"reuni[ãa]o de pais|pediatra|oftalmo|passeio|festa)\b", re.I)


def classificar_agenda(titulo: str, descricao: str = "", agenda: Optional[str] = None) -> str:
    """Retorna a chave canônica da agenda: 'pessoal', 'familia', 'trabalho', 'sie' ou 'viagem'."""
    if agenda:
        a = agenda.strip().lower()
        if any(x in a for x in ("sie", "sié", "joy")):
            return "sie"
        if any(x in a for x in ("viag", "voo", "hotel", "trip")):
            return "viagem"
        if any(x in a for x in ("trab", "work", "prof", "comerc")):
            return "trabalho"
        if any(x in a for x in ("fam", "filh", "casal", "luisa")):
            return "familia"
        if any(x in a for x in ("pess", "geral", "minha", "primary", "saud", "treino", "acad")):
            return "pessoal"
    txt = f"{titulo} {descricao}"
    if _RX_SIE.search(txt):
        return "sie"
    if _RX_VIAGEM.search(txt):
        return "viagem"
    if _RX_TRABALHO.search(txt):
        return "trabalho"
    if _RX_FAMILIA.search(txt):
        return "familia"
    return "pessoal"


def envolve_luisa(titulo: str, descricao: str = "", flag: Optional[bool] = None, categoria: str = "") -> bool:
    """flag explícito (True/False) manda; trabalho por padrão é False; sem flag, decide pelo assunto."""
    if flag is not None:
        return bool(flag)
    cat = categoria or classificar_agenda(titulo, descricao)
    if cat == "trabalho":
        return False
    return bool(_ENVOLVE.search(f"{titulo} {descricao}"))


def deve_perguntar_luisa(categoria: str, convidou_luisa: bool, flag: Optional[bool] = None) -> bool:
    """Se o Paulo não especificou com_luisa (True/False) e não convidou, lembra/pergunta em Pessoal, Família, SIÉ-Joy e Viagem."""
    if flag is not None or convidou_luisa:
        return False
    return categoria in ("pessoal", "familia", "sie", "viagem")


def quem_e(texto: str) -> list:
    t = texto.lower()
    return [nome for nome, apelidos in FILHOS.items() if any(re.search(rf"\b{re.escape(a)}\b", t) for a in apelidos)]
