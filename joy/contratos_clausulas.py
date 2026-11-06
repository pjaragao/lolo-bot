"""Biblioteca de cláusulas dos contratos do Lolo (texto jurídico fixo; o LLM só fornece os dados).

Cada cláusula é uma função `f(c) -> (titulo, itens)` ou None (pular). `c` é o contexto montado em `contratos.py`
(partes c.p1/c.p2 com artigos já flexionados: c.p2.o = "a CONTRATADA", c.p2.ao = "à CONTRATADA", c.p2.pelo, c.p2.do, c.p2.x).
Itens: str = item numerado (1.1, 1.2...), ("a", [textos]) = alíneas a), b)... do item anterior, ("p", texto) = parágrafo solto.

Base legal conferida em out/2026 (REVISADO). Revisar a cada 6 meses: Reforma Tributária (LC 214/2025) e resoluções da ANPD.
"""
from typing import Any, Callable, Dict, List, Optional, Tuple

REVISADO = "2026-10-29"
Itens = List[Any]
Clausula = Optional[Tuple[str, Itens]]


# =========================================================================== serviços (e comuns)
def objeto(c) -> Clausula:
    ct, cd = c.p1, c.p2
    obj = c.req("objeto", "objeto do contrato (o que será feito)")
    for pref in ("a prestação de ", "prestação de ", "a prestacao de ", "prestacao de "):
        if obj.lower().startswith(pref):
            obj = obj[len(pref):]
    escopo = c.lista("escopo")
    itens: Itens = []
    if escopo and c.completo:
        itens.append(f"O presente contrato tem por objeto a prestação, {cd.pelo} {ct.ao}, de {obj}, conforme escopo, "
                     "entregáveis e prazos descritos no Anexo I, que integra este contrato.")
    elif escopo:
        itens.append(f"O presente contrato tem por objeto a prestação, {cd.pelo} {ct.ao}, de {obj}, compreendendo:")
        itens.append(("a", escopo))
    else:
        itens.append(f"O presente contrato tem por objeto a prestação, {cd.pelo} {ct.ao}, de {obj}.")
    itens.append(f"{cd.O} executará os serviços com autonomia técnica, observando as diretrizes, premissas e informações "
                 f"fornecidas {ct.pelo}, as normas técnicas aplicáveis e a legislação vigente.")
    if c.g("local_execucao"):
        itens.append(f"Os serviços serão executados em {c.g('local_execucao')}.")
    itens.append("Serviços não previstos neste objeto dependerão de termo aditivo ou de proposta específica aprovada por "
                 "escrito pelas partes, com preço e prazo próprios.")
    return "DO OBJETO", itens


def escopo_aceite(c) -> Clausula:
    ct, cd = c.p1, c.p2
    dias = c.inteiro("aceite_dias", "prazo de aceite das entregas (dias úteis)", 5)
    return "DOS ENTREGÁVEIS E DO ACEITE", [
        (f"Os entregáveis, etapas e prazos estão descritos no Anexo I. {cd.O} comunicará por escrito a conclusão de cada "
         "entrega." if c.lista("escopo") or c.lista("entregas") else
         f"{cd.O} comunicará por escrito a conclusão de cada entrega ou etapa dos serviços."),
        f"{ct.O} terá {c.qtd(dias, 'dias úteis', 'dia útil')}, contados do recebimento, para aprovar a entrega ou apontar, "
        "de forma fundamentada, os ajustes necessários; não havendo manifestação nesse prazo, a entrega será considerada aceita.",
        f"Os ajustes apontados que estejam dentro do escopo serão feitos {cd.pelo} sem custo adicional, em prazo razoável "
        "combinado entre as partes, reiniciando-se o prazo de aceite apenas para os itens ajustados.",
        f"O aceite não exime {cd.o} de responder por vícios ocultos, nos termos da lei.",
    ]


def preco(c) -> Clausula:
    ct, cd = c.p1, c.p2
    serv = "dos serviços e pela licença de uso de imagem" if c.tipo == "influenciador" else "dos serviços"
    itens: Itens = []
    vm = c.valor("valor_mensal")
    if vm:
        dia = c.inteiro("dia_vencimento", "dia de vencimento da mensalidade", 10)
        itens.append(f"Pela prestação {serv}, {ct.o} pagará {cd.ao} o valor mensal de {c.money(vm)}, com vencimento "
                     f"no dia {dia} do mês seguinte ao da prestação dos serviços.")
    else:
        vg = c.valor("valor", "valor do contrato")
        parcelas = c.parcelas(vg)
        base = f"Pela prestação {serv}, {ct.o} pagará {cd.ao} o valor global e fixo de {c.money(vg)}"
        if len(parcelas) > 1:
            itens.append(base + ", da seguinte forma:")
            itens.append(("a", [f"{p['descricao']}: {c.pct(p['pct'])} do valor global, equivalente a {c.money(p['valor'])}, "
                                f"com vencimento {p['quando']}" for p in parcelas]))
        else:
            quando = (parcelas[0]["quando"] if parcelas else
                      c.req("quando_pagamento", "quando o pagamento é devido", "após a conclusão e o aceite dos serviços"))
            itens.append(base + f", em parcela única, com vencimento {quando}.")
    prazo = c.inteiro("prazo_pagamento_dias", "prazo de pagamento após a nota fiscal (dias)", 15)
    itens.append(f"Os pagamentos serão feitos mediante emissão da respectiva nota fiscal, por transferência bancária ou PIX "
                 f"para conta de titularidade {cd.do}, em até {c.qtd(prazo, 'dias corridos', 'dia corrido')} contados da "
                 "emissão e do envio da nota fiscal correspondente.")
    if c.completo and c.tipo != "influenciador":
        if c.g("despesas_reembolsaveis"):
            itens.append(f"Despesas de viagem, hospedagem e deslocamento necessárias à execução serão reembolsadas {ct.pelo} "
                         "somente se aprovadas previamente por escrito e comprovadas por documentos fiscais.")
        else:
            itens.append("O preço inclui todos os custos diretos e indiretos necessários à execução do objeto, inclusive "
                         f"deslocamentos, equipe, encargos e tributos, nada mais sendo devido {cd.ao} além do previsto "
                         "neste contrato.")
    if c.g("permuta"):
        itens.append(f"Além do valor acima, {ct.o} entregará {cd.ao}, a título de permuta, {c.g('permuta')}.")
    return "DO PREÇO E DAS CONDIÇÕES DE PAGAMENTO", itens


def tributos(c) -> Clausula:
    ct, cd = c.p1, c.p2
    regime = str(cd.d.get("regime") or "").lower()
    itens: Itens = [
        "Os tributos devidos em razão deste contrato são de responsabilidade do contribuinte definido na legislação tributária.",
        f"{ct.O} efetuará as retenções na fonte exigidas por lei (como IRRF, PIS/Cofins/CSLL, contribuição previdenciária e "
        "ISS, quando aplicáveis), que serão destacadas na nota fiscal e abatidas do valor bruto, servindo os comprovantes de "
        "recolhimento como quitação da parcela retida.",
    ]
    if "simples" in regime:
        itens.append(f"{cd.O} declara ser optante pelo Simples Nacional e se obriga a comunicar imediatamente eventual "
                     "exclusão desse regime.")
    else:
        itens.append(f"{cd.O} informará seu regime tributário e comunicará qualquer alteração que afete as retenções.")
    return "DOS TRIBUTOS", itens


def reajuste(c) -> Clausula:
    indice = c.g("indice_reajuste") or "IPCA/IBGE"
    if c.valor("valor_mensal") or c.meses_vigencia() > 12 or c.tipo in ("fornecimento", "consignacao"):
        return "DO REAJUSTE", [
            f"Os valores deste contrato serão reajustados a cada período de 12 (doze) meses, contado da data de assinatura, "
            f"pela variação acumulada do {indice} no período, ou do índice que oficialmente o substituir, nos termos da "
            "Lei nº 10.192/2001."]
    return "DO REAJUSTE", [
        "Caso a execução deste contrato ultrapasse 12 (doze) meses da data de assinatura, o saldo ainda não faturado será "
        f"reajustado pela variação acumulada do {indice} no período, ou do índice que oficialmente o substituir, nos termos "
        "da Lei nº 10.192/2001."]


def mora(c) -> Clausula:
    ct, cd = c.p1, c.p2
    multa = c.num("multa_mora_percentual", "multa por atraso (%)", 2)
    if c.consumidor and multa > 2:
        c.aviso("Relação de consumo: a multa por atraso foi limitada a 2% (CDC, art. 52, § 1º).")
        multa = 2
    juros = c.num("juros_mes_percentual", "juros de mora ao mês (%)", 1)
    itens: Itens = [
        f"O atraso no pagamento sujeitará o valor devido a multa moratória de {c.pct(multa)}, juros de mora de "
        f"{c.pct(juros)} ao mês, calculados pro rata die, e correção monetária pela variação do IPCA, desde o vencimento "
        "até o efetivo pagamento."]
    if c.completo and c.tipo == "servicos":
        dias = c.inteiro("dias_suspensao", "atraso que permite suspender os serviços (dias)", 30)
        itens.append(f"O atraso superior a {c.qtd(dias, 'dias', 'dia')} faculta {cd.ao} suspender a execução dos serviços, "
                     "mediante aviso prévio por escrito, até a regularização, sem prejuízo da rescisão prevista neste contrato.")
    return "DO ATRASO NO PAGAMENTO", itens


def vigencia(c) -> Clausula:
    v = c.g("vigencia") or {}
    if not isinstance(v, dict):
        v = {"texto": str(v)}
    inicio = f"a partir de {c.data_ext(v['inicio'])}" if v.get("inicio") else "a partir da data de sua assinatura"
    padrao = {
        "servicos": "até a conclusão e o aceite final de todos os serviços objeto deste instrumento",
        "influenciador": "até a conclusão da última entrega e o término do prazo de licença de uso de imagem",
    }
    aviso = c.inteiro("aviso_previo_dias", "aviso prévio (dias)", 30)
    if v.get("fim"):
        txt = f"Este contrato vigora {inicio} até {c.data_ext(v['fim'])}."
    elif v.get("meses") or c.tipo in ("fornecimento", "consignacao") and not v.get("texto"):
        meses = int(v.get("meses") or c.padrao("vigência (meses)", 12))
        txt = f"Este contrato vigora pelo prazo de {c.qtd(meses, 'meses', 'mês')}, contado {inicio.replace('a partir ', '')}"
        if v.get("renovacao_automatica", c.tipo in ("fornecimento", "consignacao")):
            txt += (", renovando-se automaticamente por iguais períodos, salvo manifestação em contrário de qualquer das "
                    f"partes com antecedência mínima de {c.qtd(aviso, 'dias', 'dia')} do término")
        txt += "."
    else:
        txt = f"Este contrato vigora {inicio} {v.get('texto') or padrao.get(c.tipo, 'até o cumprimento integral das obrigações das partes')}"
        txt = txt.rstrip(".") + (f", com previsão de conclusão em {v['previsao']}" if v.get("previsao") else "") + "."
    itens: Itens = [txt]
    if c.completo:
        itens.append("As obrigações de confidencialidade, de proteção de dados pessoais e as demais que, por sua natureza, "
                     "devam subsistir permanecerão válidas após o término deste contrato, pelos prazos nelas previstos.")
    return "DO PRAZO DE VIGÊNCIA", itens


def obrigacoes(c) -> Clausula:
    ct, cd = c.p1, c.p2
    oc = ["executar os serviços com zelo, diligência e boa técnica, nos prazos combinados",
          f"manter {ct.o} informad{ct.x} sobre o andamento dos serviços e comunicar prontamente qualquer fato que possa "
          "afetar prazos ou resultados"]
    if c.completo:
        oc += ["responsabilizar-se integralmente por sua equipe, prepostos e eventuais subcontratados autorizados",
               "manter, durante toda a vigência, a regularidade fiscal e as habilitações exigidas para a execução dos serviços"]
    oc += ["cumprir a legislação aplicável à sua atividade"] + c.lista("obrigacoes_contratada")
    ot = ["fornecer, em tempo hábil, as informações, documentos e acessos necessários à execução dos serviços",
          "efetuar os pagamentos nas condições e prazos ajustados"]
    if c.completo:
        ot += ["indicar um responsável para acompanhar a execução dos serviços e aprovar as entregas",
               "analisar as entregas nos prazos previstos neste contrato"]
    ot += c.lista("obrigacoes_contratante")
    return "DAS OBRIGAÇÕES DAS PARTES", [f"São obrigações {cd.do}:", ("a", oc), f"São obrigações {ct.do}:", ("a", ot)]


def rescisao(c) -> Clausula:
    ct, cd = c.p1, c.p2
    aviso = c.inteiro("aviso_previo_dias", "aviso prévio (dias)", 30)
    sanar = c.inteiro("prazo_sanar_dias", "prazo para sanar descumprimento (dias)", 10)
    hip = [f"descumprimento de obrigação contratual não sanado em até {c.qtd(sanar, 'dias', 'dia')} do recebimento de "
           "notificação da parte prejudicada",
           "decretação de falência, deferimento de recuperação judicial ou insolvência de qualquer das partes"]
    if c.completo:
        hip += ["violação das cláusulas de confidencialidade, de proteção de dados pessoais ou anticorrupção",
                "caso fortuito ou força maior que impeça a execução por mais de 30 (trinta) dias"]
    efeito = {
        "servicos": f"{ct.o} pagará {cd.ao} os serviços efetivamente prestados e aceitos até a data da extinção, "
                    f"deduzidos os valores já pagos, e {cd.o} entregará os trabalhos produzidos até então",
        "influenciador": f"{ct.o} pagará {cd.ao} as entregas já publicadas e aprovadas, deduzidos os valores já pagos",
        "fornecimento": f"{ct.o} pagará os produtos entregues e aceitos até a data da extinção, e {cd.o} atenderá os pedidos "
                        f"já aceitos, salvo se a rescisão decorrer de culpa {cd.do}",
        "consignacao": f"as partes farão o acerto final das vendas em até 10 (dez) dias, e {cd.o} devolverá {ct.ao} os "
                       "produtos não vendidos no mesmo prazo",
    }.get(c.tipo, "as partes farão o acerto das obrigações cumpridas até a data da extinção")
    return "DA RESCISÃO", [
        f"Qualquer das partes poderá resilir este contrato, sem justa causa, mediante aviso prévio por escrito de "
        f"{c.qtd(aviso, 'dias', 'dia')}, observado o art. 473 do Código Civil.",
        "Este contrato poderá ser rescindido de imediato, por notificação escrita, independentemente de aviso prévio, nas "
        "seguintes hipóteses (art. 474 do Código Civil):",
        ("a", hip),
        f"Em qualquer hipótese de término, {efeito}, sem prejuízo das penalidades e da indenização por perdas e danos cabíveis.",
    ]


def multa(c) -> Clausula:
    p = c.num("multa_percentual", "multa por descumprimento (%)", 10)
    if p > 100:
        c.aviso("Multa acima de 100% do valor da obrigação é vedada (CC, art. 412): limitei a 100%.")
        p = 100
    elif p > 20:
        c.aviso(f"Multa de {c.pct_curto(p)} é alta e tende a ser reduzida pelo juiz (CC, art. 413).")
    return "DAS PENALIDADES", [
        f"A parte que descumprir obrigação deste contrato pagará à outra multa compensatória de {c.pct(p)} {c.ref_valor()}, "
        "que valerá como mínimo da indenização, podendo a parte prejudicada exigir indenização suplementar mediante prova do "
        "prejuízo excedente (art. 416, parágrafo único, do Código Civil).",
        "Se a obrigação tiver sido cumprida em parte, a multa será reduzida proporcionalmente (art. 413 do Código Civil).",
        "A multa desta cláusula não se aplica ao simples atraso no pagamento, regido pela cláusula DO ATRASO NO PAGAMENTO.",
    ]


def limitacao(c) -> Clausula:
    return "DA RESPONSABILIDADE", [
        "Cada parte responde pelos danos diretos que comprovadamente causar à outra por culpa ou dolo na execução deste contrato.",
        "Salvo em caso de dolo, culpa grave, violação de confidencialidade ou de proteção de dados pessoais, ou de danos a "
        f"terceiros, a responsabilidade total de cada parte por este contrato fica limitada {c.ref_valor('ao')}, não "
        "respondendo nenhuma das partes por lucros cessantes ou danos indiretos.",
    ]


def forca_maior(c) -> Clausula:
    return "DO CASO FORTUITO E DA FORÇA MAIOR", [
        "Nenhuma das partes responderá pelo descumprimento causado por caso fortuito ou força maior, nos termos do art. 393 "
        "do Código Civil, desde que comunique a outra por escrito em até 5 (cinco) dias úteis do evento, informando seus "
        "efeitos e a previsão de normalização.",
        "As obrigações afetadas ficam suspensas enquanto durar o impedimento, o que não se aplica às obrigações de pagamento "
        "já vencidas; se o impedimento ultrapassar 30 (trinta) dias, qualquer das partes poderá rescindir o contrato sem "
        "penalidades, pagas as obrigações já cumpridas.",
    ]


def autonomia(c) -> Clausula:
    ct, cd = c.p1, c.p2
    if cd.pj:
        itens: Itens = [
            "Este contrato tem natureza civil e não gera vínculo empregatício, societário, associativo ou de representação "
            f"entre as partes, nem entre {ct.o} e os sócios, empregados, prepostos ou subcontratados {cd.do}.",
            f"{cd.O} organizará a execução do objeto com autonomia, definindo os meios, a equipe e a forma de trabalho, "
            "observados os prazos e requisitos deste contrato.",
            f"{cd.O} é a única responsável pelos encargos trabalhistas, previdenciários, fiscais e securitários relativos aos "
            f"seus profissionais e ressarcirá {ct.o} por qualquer condenação ou despesa que lhe seja imposta a esse título, "
            "inclusive custas e honorários advocatícios.",
        ]
    else:
        itens = [
            f"Este contrato tem natureza civil e não gera vínculo empregatício entre as partes. {cd.O} presta os serviços "
            "com autonomia, sem subordinação, exclusividade ou controle de jornada, assumindo os riscos de sua atividade "
            "(art. 442-B da Consolidação das Leis do Trabalho).",
            f"{cd.O} é responsável pelo recolhimento dos tributos e contribuições incidentes sobre a sua remuneração, "
            "ressalvadas as retenções que a lei atribuir à fonte pagadora.",
        ]
    return "DA INEXISTÊNCIA DE VÍNCULO EMPREGATÍCIO", itens


def confidencialidade(c) -> Clausula:
    anos = c.inteiro("sigilo_anos", "prazo do sigilo após o fim (anos)", 5)
    itens: Itens = [
        "As partes obrigam-se, por si, seus sócios, empregados, prepostos e eventuais subcontratados, a manter sigilo sobre "
        "as informações técnicas, comerciais, financeiras, estratégicas e pessoais a que tiverem acesso em razão deste "
        "contrato (“Informações Confidenciais”), utilizando-as exclusivamente para a sua execução.",
        "Não são Informações Confidenciais as que: (i) sejam ou se tornem públicas sem culpa da parte que as recebeu; "
        "(ii) já fossem de seu conhecimento legítimo antes da contratação; (iii) sejam recebidas legitimamente de terceiros "
        "sem dever de sigilo; ou (iv) devam ser reveladas por ordem judicial ou exigência legal, caso em que a parte "
        "comunicará previamente a outra, quando permitido, e revelará apenas o estritamente necessário.",
        f"A obrigação de sigilo vigora durante este contrato e por {c.qtd(anos, 'anos', 'ano')} após o seu término. Ao final, "
        "as Informações Confidenciais serão devolvidas ou eliminadas, a pedido da parte que as revelou, ressalvada a guarda "
        "exigida por lei.",
    ]
    if c.completo:
        itens.append("A violação desta cláusula autoriza a rescisão imediata do contrato, sem prejuízo da multa e da "
                     "indenização por perdas e danos.")
    return "DA CONFIDENCIALIDADE", itens


def lgpd(c) -> Clausula:
    ct, cd = c.p1, c.p2
    L = c.g("lgpd") or {}
    if not isinstance(L, dict):
        L = {}
    base = ("As partes tratarão os dados pessoais a que tiverem acesso em razão deste contrato apenas para executá-lo e "
            "cumprir obrigações legais, com base legal adequada (art. 7º da Lei nº 13.709/2018 – Lei Geral de Proteção de "
            "Dados Pessoais – LGPD), observadas a LGPD e as normas da Autoridade Nacional de Proteção de Dados (ANPD).")
    fim = ("Encerrado o contrato, os dados pessoais serão eliminados ou devolvidos, salvo quando a sua conservação for "
           "exigida por lei ou necessária ao exercício regular de direitos (art. 16 da LGPD).")
    if not c.completo:
        return "DA PROTEÇÃO DE DADOS PESSOAIS", [
            base,
            "Cada parte adotará medidas de segurança técnicas e administrativas aptas a proteger os dados pessoais contra "
            "acessos não autorizados e situações acidentais ou ilícitas, e comunicará à outra, em até 48 (quarenta e oito) "
            "horas da ciência, qualquer incidente de segurança que envolva dados relacionados a este contrato.",
            fim,
        ]
    itens: Itens = [base]
    if str(L.get("papel") or "").lower().startswith("oper"):
        itens += [
            f"Para a execução deste contrato, {cd.o} tratará dados pessoais em nome {ct.do}, atuando como operador{cd.a_} e "
            f"{ct.o} como controlador{ct.a_} (art. 5º, VI e VII, da LGPD).",
            f"{cd.O} tratará os dados apenas conforme as instruções documentadas {ct.do} e para as finalidades deste "
            "contrato, observado o Anexo de Tratamento de Dados Pessoais, e não os utilizará para finalidade própria "
            "(art. 39 da LGPD).",
            f"{cd.O} não contratará suboperador sem autorização prévia e por escrito {ct.do} e assegurará que os "
            "suboperadores autorizados assumam as mesmas obrigações deste contrato, respondendo por eles.",
            f"{cd.O} auxiliará {ct.o} no atendimento aos direitos dos titulares (art. 18 da LGPD), encaminhando-lhe em até "
            "2 (dois) dias úteis as solicitações recebidas, manterá registro das operações de tratamento (art. 37) e "
            "fornecerá as informações necessárias a relatórios de impacto, auditorias e fiscalizações.",
        ]
    else:
        itens.append("Cada parte atua como controladora independente dos dados pessoais que tratar para as suas próprias "
                     "finalidades, inclusive os de seus representantes e colaboradores indicados neste contrato, e "
                     "responde individualmente pelo cumprimento da LGPD.")
    if L.get("sensiveis"):
        itens.append("O tratamento de dados pessoais sensíveis somente ocorrerá nas hipóteses do art. 11 da LGPD, com "
                     "acesso restrito e medidas de segurança reforçadas.")
    itens += [
        "As partes adotarão medidas de segurança técnicas e administrativas compatíveis com a natureza dos dados e com o "
        "estado da técnica (art. 46 da LGPD), incluindo controle de acesso, registro de acessos e dever de sigilo dos "
        "profissionais envolvidos.",
        "A parte que tomar ciência de incidente de segurança envolvendo dados pessoais relacionados a este contrato "
        "comunicará a outra em até 48 (quarenta e oito) horas, com as informações disponíveis, e cooperará para que o "
        "controlador comunique a ANPD e os titulares no prazo de 3 (três) dias úteis da Resolução CD/ANPD nº 15/2024, "
        "quando o incidente puder acarretar risco ou dano relevante.",
    ]
    if L.get("transferencia_internacional") or L.get("paises"):
        paises = f" (países: {L['paises']})" if L.get("paises") else ""
        itens.append(f"A transferência internacional de dados pessoais{paises} observará os arts. 33 a 36 da LGPD; quando "
                     "fundada em cláusulas-padrão contratuais, as partes adotarão integralmente as cláusulas aprovadas pela "
                     "ANPD (Resolução CD/ANPD nº 19/2024), que passam a integrar este contrato como anexo.")
        c.aviso("Transferência internacional: anexe ao contrato o texto oficial das cláusulas-padrão da ANPD "
                "(Resolução CD/ANPD nº 19/2024), que deve ser usado na íntegra.")
    else:
        itens.append("Nenhuma das partes transferirá dados pessoais relacionados a este contrato para fora do Brasil sem "
                     "prévia comunicação à outra e sem observar os arts. 33 a 36 da LGPD.")
    enc = L.get("encarregados") if isinstance(L.get("encarregados"), dict) else {}
    e1 = enc.get("contratante") or enc.get("p1") or ct.email or c.pendente(f"encarregado/canal LGPD {ct.do}")
    e2 = enc.get("contratada") or enc.get("p2") or cd.email or c.pendente(f"encarregado/canal LGPD {cd.do}")
    itens += [
        "Cada parte indica, a seguir, o seu encarregado pelo tratamento de dados pessoais ou, se dispensada nos termos da "
        "Resolução CD/ANPD nº 2/2022, o seu canal de comunicação sobre proteção de dados (art. 41 da LGPD e Resolução "
        f"CD/ANPD nº 18/2024): {ct.R}: {e1}; {cd.R}: {e2}.",
        "A parte que, em violação à LGPD ou a este contrato, causar dano em razão do tratamento de dados pessoais responderá "
        "por ele, assegurado o direito de regresso da parte que vier a indenizar o titular (arts. 42 a 45 da LGPD).",
        fim,
    ]
    return "DA PROTEÇÃO DE DADOS PESSOAIS", itens


def pi(c) -> Clausula:
    ct, cd = c.p1, c.p2
    regime = str(c.g("pi") or "cessao").lower()
    ent = ("os relatórios, estudos, modelos, planilhas, códigos, desenhos, materiais e demais entregáveis produzidos "
           "especificamente para este contrato")
    if regime.startswith("lic"):
        itens: Itens = [f"{cd.O} mantém a titularidade dos direitos patrimoniais sobre {ent} e concede {ct.ao}, a partir do "
                        "pagamento da respectiva etapa, licença não exclusiva, irrevogável e por prazo indeterminado para "
                        "usá-los, reproduzi-los e adaptá-los para as suas atividades (Lei nº 9.610/1998 e Lei nº 9.609/1998)."]
    elif regime.startswith(("contratad", "prestador")):
        itens = [f"Os direitos de propriedade intelectual sobre {ent} permanecem com {cd.o}, que concede {ct.ao} licença de "
                 "uso interno, não exclusiva e intransferível, durante a vigência deste contrato."]
    else:
        itens = [f"Os direitos patrimoniais sobre {ent} ficam cedidos {ct.ao}, em caráter total, definitivo e exclusivo, a "
                 "partir do pagamento da respectiva etapa, incluídos os direitos de uso, reprodução, adaptação e "
                 "distribuição, sem limite de território ou de prazo (arts. 49 e 50 da Lei nº 9.610/1998 e art. 4º da "
                 "Lei nº 9.609/1998).",
                 f"{cd.O} conserva a titularidade de metodologias, ferramentas, modelos-base e conhecimentos preexistentes ou "
                 f"de uso geral, concedendo {ct.ao} licença não exclusiva, gratuita e por prazo indeterminado para utilizá-los "
                 "no que for necessário ao uso dos entregáveis."]
    itens.append(f"{cd.O} declara que os entregáveis não violam direitos de terceiros e responderá por eventuais "
                 "reclamações nesse sentido.")
    return "DA PROPRIEDADE INTELECTUAL", itens


def anticorrupcao(c) -> Clausula:
    return "DA CONDUTA ÉTICA E ANTICORRUPÇÃO", [
        "As partes declaram conhecer e se obrigam a cumprir a Lei nº 12.846/2013 (Lei Anticorrupção), o Decreto nº "
        "11.129/2022 e as demais normas de prevenção à corrupção e à lavagem de dinheiro, abstendo-se, por si e por seus "
        "administradores, empregados e prepostos, de oferecer, prometer, dar, solicitar ou receber vantagem indevida, direta "
        "ou indiretamente, em relação a este contrato.",
        "As partes declaram, ainda, que não utilizam trabalho infantil nem trabalho em condições análogas à de escravo em "
        "suas atividades.",
        "A violação desta cláusula autoriza a rescisão imediata do contrato pela parte inocente, sem prejuízo da apuração de "
        "perdas e danos.",
    ]


def nao_aliciamento(c) -> Clausula:
    meses = c.inteiro("nao_aliciamento_meses", "prazo do não aliciamento (meses)", 12)
    return "DA NÃO CONTRATAÇÃO DE PROFISSIONAIS", [
        f"Durante a vigência deste contrato e por {c.qtd(meses, 'meses', 'mês')} após o seu término, nenhuma das partes "
        "contratará ou aliciará, direta ou indiretamente, empregados ou profissionais da outra que tenham atuado na execução "
        "deste contrato, salvo com anuência por escrito."]


def nao_concorrencia(c) -> Clausula:
    ct, cd = c.p1, c.p2
    nc = c.g("nao_concorrencia") or {}
    if not isinstance(nc, dict):
        nc = {}
    meses = nc.get("meses") or c.pendente("não concorrência: prazo em meses")
    meses_txt = c.qtd(int(meses), "meses", "mês") if str(meses).isdigit() else meses
    terr = nc.get("territorio") or c.pendente("não concorrência: território")
    ativ = nc.get("atividade") or c.pendente("não concorrência: atividade restrita")
    return "DA NÃO CONCORRÊNCIA", [
        f"{cd.O} se obriga a não prestar, durante a vigência deste contrato e por {meses_txt} após o seu término, serviços "
        f"de {ativ} a concorrentes diretos {ct.do} no território de {terr}.",
        "As partes reconhecem que esta restrição é limitada no tempo, no território e no objeto, e que a sua contrapartida "
        "está incluída na remuneração deste contrato.",
    ]


def cessao(c) -> Clausula:
    ct, cd = c.p1, c.p2
    itens: Itens = ["Nenhuma das partes poderá ceder ou transferir, total ou parcialmente, os direitos e obrigações deste "
                    "contrato sem a prévia anuência, por escrito, da outra."]
    if c.tipo in ("servicos", "influenciador"):
        itens.append(f"{cd.O} somente poderá subcontratar parte do objeto com autorização prévia e por escrito {ct.do}, "
                     f"permanecendo integralmente responsável perante {ct.o} pelo que for subcontratado.")
    return "DA CESSÃO E DA SUBCONTRATAÇÃO", itens


def reforma_tributaria(c) -> Clausula:
    if 0 < c.meses_vigencia() <= 12 and not c.valor("valor_mensal"):
        return None
    return "DO EQUILÍBRIO ECONÔMICO-FINANCEIRO E DA REFORMA TRIBUTÁRIA", [
        "Os preços deste contrato foram formados considerando a legislação tributária vigente na data de sua assinatura. A "
        "criação, extinção ou alteração de tributos, inclusive a substituição gradual de PIS, Cofins, IPI, ICMS e ISS pela "
        "Contribuição sobre Bens e Serviços (CBS) e pelo Imposto sobre Bens e Serviços (IBS), nos termos da Emenda "
        "Constitucional nº 132/2023 e da Lei Complementar nº 214/2025, que comprovadamente altere o custo tributário das "
        "partes ensejará a revisão dos preços, para mais ou para menos, de modo a restabelecer o equilíbrio original.",
        "A parte interessada apresentará a demonstração do impacto, e as partes negociarão de boa-fé o novo preço em até 30 "
        "(trinta) dias; não havendo acordo, qualquer delas poderá resilir o contrato sem penalidades, observado o aviso "
        "prévio deste contrato.",
        "As partes cooperarão para viabilizar o aproveitamento de créditos de IBS e CBS, inclusive com a emissão de "
        "documentos fiscais com as informações exigidas pela legislação.",
    ]


def cdc(c) -> Clausula:
    ct = c.p1
    itens: Itens = ["Aplica-se a este contrato o Código de Defesa do Consumidor (Lei nº 8.078/1990), e as suas cláusulas "
                    f"serão interpretadas da maneira mais favorável {ct.ao} (art. 47 do CDC)."]
    if c.g("fora_estabelecimento"):
        itens.append(f"Quando a contratação ocorrer fora do estabelecimento comercial, inclusive pela internet ou por "
                     f"telefone, {ct.o} poderá desistir dela no prazo de 7 (sete) dias contados da assinatura ou do "
                     "recebimento do produto ou serviço, com a devolução imediata dos valores pagos, atualizados "
                     "(art. 49 do CDC).")
    itens.append(f"É assegurada {ct.ao} a liquidação antecipada do débito, total ou parcialmente, com redução proporcional "
                 "dos juros e demais acréscimos (art. 52, § 2º, do CDC).")
    return "DOS DIREITOS DO CONSUMIDOR", itens


def comunicacoes(c) -> Clausula:
    ct, cd = c.p1, c.p2
    e1 = ct.email or c.pendente(f"e-mail {ct.do}")
    e2 = cd.email or c.pendente(f"e-mail {cd.do}")
    return "DAS COMUNICAÇÕES", [
        "As comunicações relativas a este contrato serão feitas por escrito, inclusive por e-mail, para os endereços "
        f"eletrônicos a seguir, e serão consideradas recebidas na data do envio, salvo prova de falha na entrega: {ct.R}: "
        f"{e1}; {cd.R}: {e2}.",
        "A parte que alterar o seu endereço ou e-mail deverá comunicar a outra, sob pena de serem válidas as comunicações "
        "enviadas aos endereços aqui indicados.",
    ]


def assinatura(c) -> Clausula:
    if not c.eletronica:
        return None
    return "DA ASSINATURA ELETRÔNICA", [
        "As partes reconhecem como válida a assinatura deste instrumento por meio eletrônico, em plataforma que assegure a "
        "autoria e a integridade do documento, com ou sem certificado ICP-Brasil, nos termos do art. 10, § 2º, da Medida "
        "Provisória nº 2.200-2/2001 e da Lei nº 14.063/2020.",
        "Assinado eletronicamente com integridade conferida pelo provedor de assinatura, este instrumento constitui título "
        "executivo extrajudicial independentemente da assinatura de testemunhas (art. 784, III e § 4º, do Código de "
        "Processo Civil).",
        "Considera-se data de assinatura a da última assinatura aposta.",
    ]


def gerais(c) -> Clausula:
    itens: Itens = [
        ("Este contrato, com os seus anexos, representa o acordo integral entre as partes sobre o seu objeto e substitui "
         "propostas, negociações e entendimentos anteriores; havendo conflito, prevalece o corpo deste contrato sobre os anexos."
         if c.tem_anexos else
         "Este contrato representa o acordo integral entre as partes sobre o seu objeto e substitui propostas, negociações "
         "e entendimentos anteriores."),
        "Qualquer alteração deste contrato somente terá validade se feita por termo aditivo escrito assinado pelas partes.",
        "A tolerância de uma parte quanto ao descumprimento de qualquer obrigação pela outra não importará novação, "
        "renúncia ou alteração do pactuado.",
        "A nulidade ou a invalidade de qualquer cláusula não prejudicará as demais, que permanecerão válidas.",
        "Este contrato obriga as partes e os seus sucessores a qualquer título.",
    ]
    if c.completo and not c.consumidor:
        itens.append("As partes declaram que este contrato foi livremente negociado entre elas, em condições paritárias e "
                     "simétricas, nos termos dos arts. 421 e 421-A do Código Civil.")
    return "DAS DISPOSIÇÕES GERAIS", itens


def mediacao(c) -> Clausula:
    return "DA SOLUÇÃO AMIGÁVEL DE CONTROVÉRSIAS", [
        "As partes buscarão resolver amigavelmente qualquer controvérsia decorrente deste contrato, por negociação direta "
        "e, se necessário, por mediação, nos termos da Lei nº 13.140/2015, antes de recorrer ao Judiciário ou à arbitragem, "
        "ressalvadas as medidas urgentes.",
        "A negociação terá prazo de 30 (trinta) dias, contados da notificação da parte interessada.",
    ]


def arbitragem(c) -> Clausula:
    a = c.g("arbitragem") or {}
    if not isinstance(a, dict):
        a = {"camara": str(a)}
    camara = a.get("camara") or c.pendente("arbitragem: câmara arbitral")
    sede = a.get("cidade") or c.g("foro") or c.pendente("arbitragem: cidade-sede")
    return "DA ARBITRAGEM", [
        "Qualquer controvérsia decorrente deste contrato será resolvida definitivamente por arbitragem, administrada pela "
        f"{camara}, conforme o seu regulamento, nos termos da Lei nº 9.307/1996, por árbitro único, em língua portuguesa, "
        f"com sede em {sede}.",
        "As partes poderão recorrer ao Judiciário para medidas urgentes antes da instauração da arbitragem e para a "
        "execução da sentença arbitral, no foro eleito neste contrato.",
    ]


def foro(c) -> Clausula:
    cidade = c.req("foro", "foro (cidade/UF)", c.g("cidade") or "Florianópolis/SC")
    txt = (f"Fica eleito o foro da Comarca de {cidade} para dirimir as questões decorrentes deste contrato, com renúncia a "
           "qualquer outro, por mais privilegiado que seja")
    if c.consumidor:
        txt += f", sem prejuízo do direito {c.p1.do} de propor ação no foro do seu domicílio (art. 101, I, do CDC)"
    if c.inclui("arbitragem"):
        txt = f"Para as medidas judiciais admitidas na cláusula DA ARBITRAGEM, fica eleito o foro da Comarca de {cidade}"
    return "DO FORO", [txt + "."]


# =========================================================================== NDA
def nda_objeto(c) -> Clausula:
    fin = c.req("finalidade", "finalidade (por que as informações serão trocadas)")
    if c.mutuo:
        return "DO OBJETO", [
            f"Este acordo regula o tratamento das Informações Confidenciais que as partes trocarem entre si em razão de {fin} "
            "(a “Finalidade”).",
            "Para os fins deste acordo, considera-se PARTE REVELADORA a que divulgar Informação Confidencial e PARTE "
            "RECEPTORA a que a receber, papéis que cada parte poderá exercer.",
        ]
    return "DO OBJETO", [
        f"Este acordo regula o tratamento das Informações Confidenciais que a PARTE REVELADORA divulgar à PARTE RECEPTORA "
        f"em razão de {fin} (a “Finalidade”)."]


def nda_definicao(c) -> Clausula:
    return "DAS INFORMAÇÕES CONFIDENCIAIS", [
        "Consideram-se Informações Confidenciais todas as informações, dados, documentos, planilhas, projetos, know-how, "
        "estratégias e informações comerciais, financeiras, técnicas e pessoais, em qualquer forma ou meio, reveladas direta "
        "ou indiretamente, antes ou depois da assinatura deste acordo, identificadas ou não como confidenciais, desde que "
        "relacionadas à Finalidade.",
        "Não são Informações Confidenciais as que: (i) sejam ou se tornem públicas sem culpa da PARTE RECEPTORA; (ii) já "
        "fossem de seu conhecimento legítimo antes da revelação; (iii) sejam recebidas legitimamente de terceiros sem dever "
        "de sigilo; (iv) sejam desenvolvidas de forma independente, sem uso das Informações Confidenciais; ou (v) devam ser "
        "reveladas por ordem judicial ou exigência legal, caso em que a PARTE RECEPTORA comunicará previamente a PARTE "
        "REVELADORA, quando permitido, e revelará apenas o estritamente necessário.",
    ]


def nda_obrigacoes(c) -> Clausula:
    return "DAS OBRIGAÇÕES DA PARTE RECEPTORA", ["A PARTE RECEPTORA obriga-se a:", ("a", [
        "usar as Informações Confidenciais exclusivamente para a Finalidade",
        "restringir o acesso a sócios, administradores, empregados e assessores que precisem conhecê-las para a Finalidade, "
        "sujeitos a dever de sigilo equivalente ao deste acordo, respondendo por eles",
        "não copiar nem reproduzir as Informações Confidenciais além do necessário para a Finalidade",
        "protegê-las com o mesmo cuidado que dispensa às próprias informações sigilosas, nunca inferior a um cuidado razoável",
        "não realizar engenharia reversa de produtos, protótipos ou softwares recebidos",
        "comunicar imediatamente à PARTE REVELADORA qualquer acesso ou uso não autorizado de que tiver ciência",
    ])]


def nda_prazo(c) -> Clausula:
    meses = c.inteiro("vigencia_meses", "vigência do acordo (meses)", 24)
    anos = c.inteiro("sigilo_anos", "sigilo após o fim (anos)", 5)
    return "DO PRAZO", [
        f"Este acordo vigora por {c.qtd(meses, 'meses', 'mês')} a partir da data de sua assinatura, e as obrigações de "
        f"sigilo subsistirão por {c.qtd(anos, 'anos', 'ano')} após o seu término; quanto a segredos de negócio e a dados "
        "pessoais, enquanto mantiverem essa natureza."]


def nda_devolucao(c) -> Clausula:
    return "DA DEVOLUÇÃO DAS INFORMAÇÕES", [
        "Encerrada a Finalidade ou a pedido da PARTE REVELADORA, a PARTE RECEPTORA devolverá ou destruirá, em até 10 (dez) "
        "dias, as Informações Confidenciais e as suas cópias, confirmando por escrito, ressalvadas as cópias que deva manter "
        "por exigência legal, que continuarão sujeitas a este acordo."]


def nda_sem_licenca(c) -> Clausula:
    return "DA PROPRIEDADE DAS INFORMAÇÕES", [
        "As Informações Confidenciais continuam de propriedade da PARTE REVELADORA. A sua revelação não transfere propriedade "
        "nem concede licença sobre marcas, patentes, direitos autorais ou outros direitos de propriedade intelectual.",
        "Este acordo não obriga as partes a celebrar qualquer outro negócio, nem cria entre elas sociedade, representação ou "
        "exclusividade.",
    ]


# =========================================================================== fornecimento
def forn_objeto(c) -> Clausula:
    ct, cd = c.p1, c.p2
    prod = c.req("produtos", "produtos fornecidos")
    lista = c.lista("produtos_lista")
    itens: Itens = [f"O presente contrato tem por objeto o fornecimento, {cd.pelo} {ct.ao}, de {prod}, conforme pedidos de "
                    f"compra emitidos {ct.pelo} durante a sua vigência"
                    + (", nas especificações e preços do Anexo I, que integra este contrato." if lista else ".")]
    itens.append(f"Este contrato não obriga {ct.o} a adquirir quantidades mínimas, salvo as indicadas expressamente em "
                 "cada pedido aceito.")
    return "DO OBJETO", itens


def forn_pedidos(c) -> Clausula:
    ct, cd = c.p1, c.p2
    prazo = c.inteiro("prazo_entrega_dias", "prazo de entrega (dias)", 15)
    local = c.req("local_entrega", "local de entrega", ct.endereco or None)
    frete = str(c.g("frete") or c.padrao("frete", "CIF")).upper()
    frete_txt = (f"com frete, seguro e embalagem por conta {cd.do} (CIF)" if frete.startswith("CIF")
                 else f"com frete e seguro por conta {ct.do} (FOB), a partir do estabelecimento {cd.do}")
    return "DOS PEDIDOS E DA ENTREGA", [
        "Os pedidos serão feitos por escrito, inclusive por e-mail ou aplicativo de mensagens, e serão considerados aceitos "
        f"se não forem recusados {cd.pelo} em até 2 (dois) dias úteis do recebimento.",
        f"{cd.O} entregará os produtos em {local}, em até {c.qtd(prazo, 'dias corridos', 'dia corrido')} do aceite do "
        f"pedido, {frete_txt}, acompanhados da nota fiscal correspondente.",
        "Os riscos de perda ou avaria dos produtos correm por conta de quem for responsável pelo frete até a entrega no local "
        "indicado.",
        f"O atraso na entrega permite {ct.ao} cancelar o pedido, total ou parcialmente, sem ônus, mediante comunicação "
        "escrita, sem prejuízo das penalidades deste contrato.",
    ]


def forn_preco(c) -> Clausula:
    ct, cd = c.p1, c.p2
    prazo = c.inteiro("prazo_pagamento_dias", "prazo de pagamento (dias)", 30)
    forma = c.g("forma_pagamento") or "boleto bancário, transferência ou PIX"
    tabela = "do Anexo I" if c.lista("produtos_lista") else "da tabela vigente na data do pedido, aceita pelas partes"
    return "DOS PREÇOS E DO PAGAMENTO", [
        f"Os preços dos produtos são os {tabela} e incluem todos os tributos, embalagens e demais custos, além do frete quando "
        "este for CIF.",
        f"{ct.O} pagará cada fornecimento em até {c.qtd(prazo, 'dias corridos', 'dia corrido')} contados da entrega dos "
        f"produtos com a respectiva nota fiscal, por {forma}.",
        f"É vedado {cd.ao} emitir duplicata ou título de crédito que não corresponda a pedido aceito e a produtos efetivamente "
        f"entregues, ou levar a protesto título contestado por escrito {ct.pelo}.",
    ]


def forn_qualidade(c) -> Clausula:
    ct, cd = c.p1, c.p2
    insp = c.inteiro("inspecao_dias", "prazo para recusar produtos (dias)", 30)
    subst = c.inteiro("substituicao_dias", "prazo para substituir produtos recusados (dias)", 15)
    return "DA QUALIDADE E DA GARANTIA", [
        f"{cd.O} garante que os produtos são novos e conformes às especificações, às amostras aprovadas e à regulamentação "
        "aplicável, inclusive às regras de etiquetagem e composição exigidas para produtos têxteis, quando for o caso.",
        f"{ct.O} poderá recusar, no recebimento ou em até {c.qtd(insp, 'dias', 'dia')} dele, produtos com vício aparente, "
        "divergentes do pedido ou fora das especificações; os vícios ocultos poderão ser reclamados nos prazos legais "
        "(arts. 441 a 446 do Código Civil).",
        f"Os produtos recusados serão substituídos em até {c.qtd(subst, 'dias', 'dia')} ou terão o seu valor restituído ou "
        f"creditado, à escolha {ct.do}, com frete de retorno por conta {cd.do}.",
        f"{cd.O} responderá perante {ct.o} pelos valores pagos {ct.pelo} a consumidores em razão de defeito de "
        "fabricação ou vício de qualidade dos produtos, assegurado o direito de regresso (arts. 13, parágrafo único, e 18 do "
        "Código de Defesa do Consumidor).",
    ]


def forn_marcas(c) -> Clausula:
    ct, cd = c.p1, c.p2
    return "DAS MARCAS E DA PROPRIEDADE INTELECTUAL", [
        f"Cada parte mantém a titularidade das suas marcas. {ct.O} poderá usar as marcas, fotos e descrições dos produtos "
        "fornecidos para revendê-los e divulgá-los, inclusive em lojas físicas, sites, marketplaces e redes sociais.",
        f"{cd.O} declara que os produtos não violam marcas, desenhos industriais, direitos autorais ou outros direitos de "
        f"terceiros, e responderá integralmente por reclamações nesse sentido, ressarcindo {ct.o} pelos prejuízos sofridos.",
    ]


# =========================================================================== consignação (contrato estimatório)
def cons_objeto(c) -> Clausula:
    ct, cd = c.p1, c.p2
    prod = c.req("produtos", "produtos consignados")
    canais = c.g("canais_venda") or "em seu estabelecimento e nos seus canais de venda"
    return "DO OBJETO", [
        f"{ct.O} entrega {cd.ao}, em consignação, {prod}, descritos nos romaneios e notas fiscais de remessa emitidos "
        f"durante a vigência deste contrato, para que {cd.o} os venda a terceiros {canais}, nos termos dos arts. 534 a 537 "
        "do Código Civil.",
        "Cada romaneio, assinado ou confirmado por escrito pelas partes, integra este contrato e indica os produtos, as "
        "quantidades e os preços de venda e de repasse.",
    ]


def cons_propriedade(c) -> Clausula:
    ct, cd = c.p1, c.p2
    return "DA PROPRIEDADE DOS PRODUTOS", [
        f"Os produtos consignados permanecem de propriedade {ct.do} até a sua venda ao consumidor final e não podem ser "
        f"penhorados ou sequestrados por credores {cd.do} enquanto não pago integralmente o preço (art. 536 do Código Civil).",
        f"{ct.O} não poderá dispor dos produtos consignados antes que lhe sejam restituídos ou que lhe seja comunicada a "
        "restituição (art. 537 do Código Civil).",
    ]


def cons_precos(c) -> Clausula:
    ct, cd = c.p1, c.p2
    com = c.g("comissao_percentual")
    itens: Itens = []
    if com not in (None, ""):
        com = c.num("comissao_percentual", "comissão", 0)
        itens.append(f"Pelos produtos vendidos, {cd.o} repassará {ct.ao} o preço de venda efetivamente praticado, deduzida "
                     f"a sua comissão de {c.pct(com)}.")
    else:
        itens.append(f"Pelos produtos vendidos, {cd.o} repassará {ct.ao} o preço de repasse indicado no romaneio.")
    desc = c.g("desconto_max_percentual")
    if desc not in (None, ""):
        itens.append(f"Os produtos serão vendidos pelo preço sugerido no romaneio, admitidos descontos de até "
                     f"{c.pct(c.num('desconto_max_percentual', 'desconto máximo', 0))}; descontos maiores e promoções "
                     f"dependem de autorização por escrito {ct.do}.")
    else:
        itens.append("Os produtos serão vendidos pelo preço sugerido no romaneio; descontos e promoções dependem de "
                     f"autorização por escrito {ct.do}.")
    itens.append(f"As taxas de meios de pagamento e o risco de inadimplência do comprador final correm por conta {cd.do}, "
                 "salvo ajuste diverso por escrito.")
    return "DOS PREÇOS E DA COMISSÃO", itens


def cons_acerto(c) -> Clausula:
    ct, cd = c.p1, c.p2
    per = c.g("periodicidade_acerto") or c.padrao("periodicidade do acerto", "mensal")
    dia = c.inteiro("dia_acerto", "dia do acerto", 10)
    return "DO ACERTO DE CONTAS", [
        f"O acerto de contas será {per}, até o dia {dia} do mês seguinte ao período das vendas, com base em relatório de "
        f"vendas e de estoque enviado {cd.pelo} até 5 (cinco) dias antes, e o pagamento será feito por transferência "
        f"bancária ou PIX para conta de titularidade {ct.do}.",
        f"{ct.O} poderá conferir o estoque consignado, mediante aviso com 2 (dois) dias úteis de antecedência, e as "
        "divergências serão tratadas como produtos vendidos, salvo prova em contrário.",
    ]


def cons_guarda(c) -> Clausula:
    ct, cd = c.p1, c.p2
    prazo = c.inteiro("prazo_consignacao_dias", "prazo de consignação de cada remessa (dias)", 90)
    frete = str(c.g("frete") or "").lower()
    frete_txt = {"consignante": f"por conta {ct.do}", "consignataria": f"por conta {cd.do}",
                 "consignatário": f"por conta {cd.do}", "consignatária": f"por conta {cd.do}"}.get(
        frete, "divididos igualmente entre as partes" if frete.startswith("divid") else f"por conta {ct.do}")
    if not frete:
        c.padrao("frete da consignação", "consignante")
    return "DA GUARDA E DA DEVOLUÇÃO", [
        f"{cd.O} é responsável pela guarda e conservação dos produtos consignados e responderá pelo preço de repasse em caso "
        "de perda, furto, roubo, avaria ou extravio, ainda que decorrente de caso fortuito (art. 535 do Código Civil).",
        f"Os produtos não vendidos serão devolvidos {ct.ao} ao final do prazo de {c.qtd(prazo, 'dias', 'dia')} contados de "
        "cada remessa, ou antes, a pedido de qualquer das partes, nas mesmas condições em que foram recebidos, acompanhados "
        "da nota fiscal de retorno.",
        f"Os custos de frete de remessa e de retorno dos produtos correm {frete_txt}.",
        "As partes emitirão os documentos fiscais exigidos pela legislação para a remessa, a venda e o retorno de mercadorias "
        "em consignação.",
    ]


def cons_exposicao(c) -> Clausula:
    ct, cd = c.p1, c.p2
    return "DA EXPOSIÇÃO E DA DIVULGAÇÃO", [
        f"{cd.O} exporá os produtos de forma adequada, preservando a imagem da marca {ct.do}, e poderá fotografá-los e "
        "divulgá-los nos seus canais de venda e redes sociais."]


# =========================================================================== influenciador
def infl_objeto(c) -> Clausula:
    ct, cd = c.p1, c.p2
    marca = c.req("marca", "marca/produtos divulgados")
    plat = c.req("plataformas", "plataformas e perfis (ex.: Instagram @perfil)")
    entregas = c.lista("entregas")
    if not entregas:
        c.pendente("entregas (quantidade e formato dos conteúdos)")
    itens: Itens = [f"O presente contrato tem por objeto a criação e a publicação, {cd.pelo}, de conteúdo publicitário sobre "
                    f"{marca} nos seus perfis em {plat}, conforme as entregas abaixo, e a licença de uso da sua imagem, "
                    "nome e voz nos termos deste contrato:"]
    itens.append(("a", entregas or ["[●]"]))
    itens.append(f"Datas e roteiro básico de cada conteúdo serão combinados por escrito. A publicação depende da aprovação "
                 f"prévia do conteúdo {ct.pelo}, que se manifestará em até 2 (dois) dias úteis do recebimento.")
    perm = c.inteiro("permanencia_dias", "dias mínimos de permanência das publicações", 90)
    itens.append(f"As publicações em feed permanecerão no perfil {cd.do} por, no mínimo, {c.qtd(perm, 'dias', 'dia')}.")
    return "DO OBJETO E DAS ENTREGAS", itens


def infl_publicidade(c) -> Clausula:
    cd = c.p2
    return "DA PUBLICIDADE IDENTIFICADA", [
        "Todo conteúdo será claramente identificado como publicidade, por exemplo com #publi ou #publicidade e com a "
        "ferramenta de parceria paga da plataforma, nos termos do art. 36 do Código de Defesa do Consumidor e do Guia de "
        "Publicidade por Influenciadores Digitais do CONAR.",
        f"{cd.O} não fará afirmações sobre os produtos que não possam ser comprovadas nem promessas de resultado, e "
        "observará os termos de uso das plataformas.",
    ]


def infl_imagem(c) -> Clausula:
    ct, cd = c.p1, c.p2
    meses = c.inteiro("licenca_meses", "prazo da licença de uso de imagem (meses)", 6)
    imp = c.g("impulsionamento")
    imp = True if imp in (None, "") else bool(imp)
    usos = f"nos perfis, sites e lojas {ct.do}, em materiais de ponto de venda" + (
        " e em anúncios pagos (impulsionamento) nas plataformas digitais" if imp else "")
    return "DA LICENÇA DE USO DE IMAGEM", [
        f"{cd.O} licencia {ct.ao}, em caráter não exclusivo e com remuneração incluída no preço deste contrato, o uso da sua "
        f"imagem, nome, voz e do conteúdo produzido, {usos}, pelo prazo de {c.qtd(meses, 'meses', 'mês')} contados da "
        "primeira publicação, em território nacional (art. 20 do Código Civil).",
        f"Encerrado o prazo, {ct.o} não fará novas veiculações nem impulsionamentos, podendo manter no seu perfil as "
        "publicações orgânicas já feitas.",
        f"{cd.O} mantém a titularidade do conteúdo que produzir, sem prejuízo da licença desta cláusula.",
    ]


def infl_exclusividade(c) -> Clausula:
    cd = c.p2
    ex = c.g("exclusividade") or {}
    if not isinstance(ex, dict):
        ex = {}
    meses = ex.get("meses") or c.pendente("exclusividade: prazo em meses")
    seg = ex.get("segmento") or c.pendente("exclusividade: segmento")
    meses_txt = c.qtd(int(meses), "meses", "mês") if str(meses).isdigit() else meses
    return "DA EXCLUSIVIDADE", [
        f"Durante {meses_txt} contados da assinatura, {cd.o} não divulgará marcas concorrentes do segmento de {seg}."]


def infl_conduta(c) -> Clausula:
    ct, cd = c.p1, c.p2
    return "DA CONDUTA E DA IMAGEM DAS PARTES", [
        "As partes não praticarão atos que atentem contra a imagem e a reputação uma da outra.",
        f"Conduta pública {cd.do} que associe a marca {ct.do} a discurso de ódio, discriminação, ato ilícito ou conteúdo "
        f"ofensivo autoriza {ct.o} a rescindir este contrato de imediato e a pedir a remoção das publicações, sem multa e "
        "sem prejuízo de perdas e danos.",
    ]


def infl_metricas(c) -> Clausula:
    cd = c.p2
    return "DOS RESULTADOS", [
        f"{cd.O} enviará, em até 7 (sete) dias após cada publicação, capturas de tela ou relatório com alcance, impressões e "
        "interações do conteúdo."]


# =========================================================================== aditivo e distrato
def adit_objeto(c) -> Clausula:
    alt = c.lista("alteracoes")
    if not alt:
        c.pendente("alterações do aditivo")
        alt = ["[●]"]
    return "DO OBJETO DO ADITIVO", ["Por este Termo Aditivo, as partes alteram o Contrato nos seguintes termos:"] + alt


def adit_ratificacao(c) -> Clausula:
    return "DA RATIFICAÇÃO", [
        "Permanecem inalteradas e ratificadas as demais cláusulas e condições do Contrato que não conflitem com este Termo "
        "Aditivo, que dele passa a fazer parte integrante.",
        "Aplica-se a este Termo Aditivo a cláusula de foro do Contrato.",
    ]


def dist_objeto(c) -> Clausula:
    efeito = c.g("data_efeito")
    quando = f"com efeitos a partir de {c.data_ext(efeito)}" if efeito else "com efeitos a partir da data de assinatura deste instrumento"
    return "DO DISTRATO", [f"As partes resolvem extinguir o Contrato, de comum acordo, {quando}, nos termos do art. 472 do "
                           "Código Civil."]


def dist_acerto(c) -> Clausula:
    ct, cd = c.p1, c.p2
    a = c.g("acerto") or {}
    if not isinstance(a, dict):
        a = {"texto": str(a)}
    itens: Itens = []
    if a.get("valor"):
        quem_paga = ct if str(a.get("pagador") or "p1") in ("p1", "contratante", ct.R.lower()) else cd
        quem_recebe = cd if quem_paga is ct else ct
        itens.append(f"Para quitação das obrigações do Contrato, {quem_paga.o} pagará {quem_recebe.ao} o valor de "
                     f"{c.money(c.valor_de(a['valor']))}, {a.get('quando') or 'em até 10 (dez) dias da assinatura deste instrumento'}, "
                     "por transferência bancária ou PIX.")
    if a.get("texto"):
        itens.append(a["texto"])
    if not itens:
        itens.append("As partes declaram que não há valores pendentes entre elas em razão do Contrato.")
    return "DO ACERTO DE CONTAS", itens


def dist_quitacao(c) -> Clausula:
    return "DA QUITAÇÃO", [
        "Cumpridas as obrigações deste instrumento, as partes dão-se mútua, plena, geral e irrevogável quitação quanto ao "
        "Contrato, para nada mais reclamarem a qualquer título, ressalvadas as obrigações que, por sua natureza, subsistem ao "
        "término, como as de confidencialidade e de proteção de dados pessoais."]


def dist_finais(c) -> Clausula:
    return "DAS DISPOSIÇÕES FINAIS", ["Aplica-se a este instrumento a cláusula de foro do Contrato."]


# =========================================================================== catálogo
CLAUSULAS: Dict[str, Callable] = {f.__name__: f for f in (
    objeto, escopo_aceite, preco, tributos, reajuste, mora, vigencia, obrigacoes, rescisao, multa, limitacao, forca_maior,
    autonomia, confidencialidade, lgpd, pi, anticorrupcao, nao_aliciamento, nao_concorrencia, cessao, reforma_tributaria,
    cdc, comunicacoes, assinatura, gerais, mediacao, arbitragem, foro,
    nda_objeto, nda_definicao, nda_obrigacoes, nda_prazo, nda_devolucao, nda_sem_licenca,
    forn_objeto, forn_pedidos, forn_preco, forn_qualidade, forn_marcas,
    cons_objeto, cons_propriedade, cons_precos, cons_acerto, cons_guarda, cons_exposicao,
    infl_objeto, infl_publicidade, infl_imagem, infl_exclusividade, infl_conduta, infl_metricas,
    adit_objeto, adit_ratificacao, dist_objeto, dist_acerto, dist_quitacao, dist_finais)}

# Módulos que o Paulo pode ligar/desligar (nome amigável + base legal). S = simples, C = completo, O = opcional,
# auto = entra sozinho quando a condição existir (relação de consumo).
MODULOS: Dict[str, Tuple[str, str]] = {
    "escopo_aceite": ("Entregáveis e aceite", "—"),
    "tributos": ("Tributos e retenções", "Lei 10.833/2003 art. 30; Lei 8.212/1991 art. 31; LC 116/2003"),
    "reajuste": ("Reajuste anual", "Lei 10.192/2001"),
    "mora": ("Atraso no pagamento (multa, juros, IPCA)", "CC arts. 389 e 406 (Lei 14.905/2024)"),
    "multa": ("Multa por descumprimento", "CC arts. 408–416"),
    "limitacao": ("Limitação de responsabilidade", "CC art. 421-A (não vale em consumo)"),
    "forca_maior": ("Caso fortuito e força maior", "CC art. 393"),
    "autonomia": ("Sem vínculo empregatício", "CLT arts. 3º e 442-B"),
    "confidencialidade": ("Confidencialidade", "—"),
    "lgpd": ("Proteção de dados (LGPD)", "Lei 13.709/2018; Res. ANPD 2/2022, 15/2024, 18/2024, 19/2024"),
    "pi": ("Propriedade intelectual", "Lei 9.610/1998 arts. 49–50; Lei 9.609/1998 art. 4º"),
    "anticorrupcao": ("Anticorrupção", "Lei 12.846/2013; Decreto 11.129/2022"),
    "nao_aliciamento": ("Não contratação de profissionais", "—"),
    "nao_concorrencia": ("Não concorrência", "exige prazo, território e atividade"),
    "cessao": ("Cessão e subcontratação", "CC art. 286"),
    "reforma_tributaria": ("Reforma Tributária (IBS/CBS)", "EC 132/2023; LC 214/2025"),
    "cdc": ("Direitos do consumidor", "CDC arts. 47, 49, 52 e 101"),
    "mediacao": ("Mediação prévia", "Lei 13.140/2015"),
    "arbitragem": ("Arbitragem", "Lei 9.307/1996 (não em consumo)"),
    "forn_marcas": ("Marcas e PI dos produtos", "—"),
    "cons_exposicao": ("Exposição e divulgação", "—"),
    "infl_exclusividade": ("Exclusividade do influenciador", "exige prazo e segmento"),
    "infl_metricas": ("Relatório de resultados", "—"),
}

_COMUNS_FIM = [("comunicacoes", "S"), ("assinatura", "S"), ("gerais", "S"), ("mediacao", "O"), ("arbitragem", "O"),
               ("foro", "S")]

MODELOS: Dict[str, Dict[str, Any]] = {
    "servicos": {
        "nome": "Prestação de serviços", "titulo": "CONTRATO DE PRESTAÇÃO DE SERVIÇOS", "curto": "Contrato de Prestação de Serviços",
        "papeis": (("CONTRATANTE", "CONTRATANTE"), ("CONTRATADA", "CONTRATADO")),
        "clausulas": [("objeto", "S"), ("escopo_aceite", "C"), ("preco", "S"), ("tributos", "C"), ("reajuste", "C"),
                      ("mora", "S"), ("vigencia", "S"), ("obrigacoes", "S"), ("rescisao", "S"), ("multa", "C"),
                      ("limitacao", "C"), ("forca_maior", "C"), ("autonomia", "S"), ("confidencialidade", "S"),
                      ("lgpd", "S"), ("pi", "C"), ("anticorrupcao", "C"), ("nao_aliciamento", "O"),
                      ("nao_concorrencia", "O"), ("cessao", "C"), ("reforma_tributaria", "C"), ("cdc", "auto")] + _COMUNS_FIM,
        "dados": "objeto; escopo (lista, opcional); valor + parcelas [{descricao, percentual, quando}] OU valor_mensal + "
                 "dia_vencimento; prazo_pagamento_dias (15); vigencia {meses | fim | texto}; pi (cessao|licenca|contratada)",
    },
    "nda": {
        "nome": "Acordo de confidencialidade (NDA)", "titulo": "ACORDO DE CONFIDENCIALIDADE", "curto": "Acordo de Confidencialidade",
        "papeis": (("PARTE REVELADORA", "PARTE REVELADORA"), ("PARTE RECEPTORA", "PARTE RECEPTORA")),
        "clausulas": [("nda_objeto", "S"), ("nda_definicao", "S"), ("nda_obrigacoes", "S"), ("nda_prazo", "S"),
                      ("nda_devolucao", "S"), ("nda_sem_licenca", "S"), ("lgpd", "S"), ("multa", "C"),
                      ("anticorrupcao", "O")] + _COMUNS_FIM,
        "dados": "mutuo (true padrão); finalidade; vigencia_meses (24); sigilo_anos (5); valor_referencia para a multa (opcional)",
    },
    "fornecimento": {
        "nome": "Fornecimento de produtos", "titulo": "CONTRATO DE FORNECIMENTO DE PRODUTOS", "curto": "Contrato de Fornecimento",
        "papeis": (("COMPRADORA", "COMPRADOR"), ("FORNECEDORA", "FORNECEDOR")),
        "clausulas": [("forn_objeto", "S"), ("forn_pedidos", "S"), ("forn_preco", "S"), ("mora", "S"), ("reajuste", "C"),
                      ("forn_qualidade", "S"), ("forn_marcas", "C"), ("vigencia", "S"), ("rescisao", "S"), ("multa", "C"),
                      ("limitacao", "O"), ("forca_maior", "C"), ("confidencialidade", "C"), ("lgpd", "S"),
                      ("anticorrupcao", "C"), ("cessao", "C"), ("reforma_tributaria", "C"), ("cdc", "auto")] + _COMUNS_FIM,
        "dados": "produtos; produtos_lista (opcional, vira Anexo I); local_entrega; prazo_entrega_dias (15); frete CIF|FOB; "
                 "prazo_pagamento_dias (30); forma_pagamento; inspecao_dias (30); vigencia {meses} (12, renova)",
    },
    "consignacao": {
        "nome": "Consignação (contrato estimatório)", "titulo": "CONTRATO DE CONSIGNAÇÃO DE MERCADORIAS",
        "curto": "Contrato de Consignação",
        "papeis": (("CONSIGNANTE", "CONSIGNANTE"), ("CONSIGNATÁRIA", "CONSIGNATÁRIO")),
        "clausulas": [("cons_objeto", "S"), ("cons_propriedade", "S"), ("cons_precos", "S"), ("cons_acerto", "S"),
                      ("mora", "S"), ("cons_guarda", "S"), ("cons_exposicao", "C"), ("vigencia", "S"), ("rescisao", "S"),
                      ("multa", "C"), ("forca_maior", "C"), ("confidencialidade", "C"), ("lgpd", "S"),
                      ("anticorrupcao", "C"), ("cessao", "C"), ("reforma_tributaria", "C")] + _COMUNS_FIM,
        "dados": "produtos; comissao_percentual (da consignatária) ou preço de repasse no romaneio; prazo_consignacao_dias (90); "
                 "periodicidade_acerto (mensal); dia_acerto (10); frete consignante|consignataria|dividido; desconto_max_percentual",
    },
    "influenciador": {
        "nome": "Influenciador (publicidade + uso de imagem)",
        "titulo": "CONTRATO DE PRESTAÇÃO DE SERVIÇOS DE PUBLICIDADE E LICENÇA DE USO DE IMAGEM",
        "curto": "Contrato de Publicidade com Influenciador",
        "papeis": (("CONTRATANTE", "CONTRATANTE"), ("CONTRATADA", "CONTRATADO")),
        "clausulas": [("infl_objeto", "S"), ("infl_publicidade", "S"), ("preco", "S"), ("mora", "S"), ("infl_imagem", "S"),
                      ("infl_exclusividade", "O"), ("infl_conduta", "S"), ("infl_metricas", "C"), ("vigencia", "S"),
                      ("autonomia", "S"), ("rescisao", "S"), ("multa", "C"), ("confidencialidade", "C"), ("lgpd", "S"),
                      ("anticorrupcao", "C"), ("cessao", "C")] + _COMUNS_FIM,
        "dados": "marca; plataformas; entregas (lista); valor + parcelas; permuta (opcional); licenca_meses (6); "
                 "permanencia_dias (90); impulsionamento (true); exclusividade {meses, segmento}",
    },
    "aditivo": {
        "nome": "Termo aditivo", "titulo": "TERMO ADITIVO", "curto": "Termo Aditivo",
        "papeis": None, "clausulas": [("adit_objeto", "S"), ("adit_ratificacao", "S"), ("assinatura", "S")],
        "dados": "base_id (contrato gerado pelo Lolo) OU contrato_original {titulo, data} + partes; numero (1); "
                 "alteracoes (lista de textos, ex.: 'A cláusula 2.3 passa a vigorar com a seguinte redação: ...')",
    },
    "distrato": {
        "nome": "Distrato", "titulo": "INSTRUMENTO PARTICULAR DE DISTRATO", "curto": "Distrato",
        "papeis": None, "clausulas": [("dist_objeto", "S"), ("dist_acerto", "S"), ("dist_quitacao", "S"),
                                      ("assinatura", "S"), ("dist_finais", "S")],
        "dados": "base_id OU contrato_original {titulo, data} + partes; data_efeito; acerto {valor, pagador p1|p2, quando, texto}",
    },
}

ALIAS_TIPO = {
    "servico": "servicos", "serviço": "servicos", "serviços": "servicos", "prestacao de servicos": "servicos",
    "prestação de serviços": "servicos", "confidencialidade": "nda", "sigilo": "nda", "fornecimento": "fornecimento",
    "compra e venda": "fornecimento", "consignacao": "consignacao", "consignação": "consignacao", "estimatorio": "consignacao",
    "influenciador": "influenciador", "influencer": "influenciador", "publicidade": "influenciador", "aditivo": "aditivo",
    "termo aditivo": "aditivo", "distrato": "distrato",
}

# Checklist de revisão de contratos recebidos: (módulo, rótulo, regex no texto sem acento e minúsculo, base legal)
REVISAO = [
    ("objeto", "Objeto", r"\bobjeto\b", ""),
    ("preco", "Preço e pagamento", r"pagamento|\bpreco\b|remunerac|valor (global|mensal|total)", ""),
    ("vigencia", "Prazo / vigência", r"vigencia|vigorar|prazo de (duracao|vigencia)", "CC art. 598 (serviços: até 4 anos)"),
    ("obrigacoes", "Obrigações das partes", r"obrigac(ao|oes) d[aoe]s?", ""),
    ("rescisao", "Rescisão", r"rescis|resili|rescindi", "CC arts. 473–474"),
    ("multa", "Multa / cláusula penal", r"multa|clausula penal", "CC arts. 408–416"),
    ("mora", "Atraso: juros e correção", r"juros|correcao monetaria", "CC arts. 389 e 406 (Lei 14.905/2024)"),
    ("reajuste", "Reajuste", r"reajust", "Lei 10.192/2001"),
    ("confidencialidade", "Confidencialidade", r"sigilo|confidencia", ""),
    ("lgpd", "Proteção de dados (LGPD)", r"lgpd|13\.?709|dados pessoais", "Lei 13.709/2018"),
    ("autonomia", "Sem vínculo empregatício", r"vinculo (empregaticio|trabalhista)|442-b", "CLT arts. 3º e 442-B"),
    ("pi", "Propriedade intelectual", r"propriedade intelectual|direitos? (autorais|de autor)|9\.?610|9\.?609", "Lei 9.610/1998"),
    ("anticorrupcao", "Anticorrupção", r"anticorrup|12\.?846|vantagem indevida", "Lei 12.846/2013"),
    ("forca_maior", "Caso fortuito / força maior", r"forca maior|caso fortuito", "CC art. 393"),
    ("cessao", "Cessão / subcontratação", r"\bcess(ao|ar)\b|\bceder\b|subcontrat", "CC art. 286"),
    ("limitacao", "Limitação de responsabilidade", r"limit\w* (a |da )?responsabilidade|lucros cessantes|danos indiretos", "CC art. 421-A"),
    ("comunicacoes", "Comunicações / notificações", r"notifica|comunicac", ""),
    ("assinatura", "Assinatura eletrônica ou testemunhas", r"assinatura eletronica|meio eletronico|testemunha|icp-brasil", "CPC art. 784, III e § 4º"),
    ("reforma_tributaria", "Reforma Tributária (IBS/CBS)", r"\bibs\b|\bcbs\b|reforma tributaria|214/2025", "EC 132/2023; LC 214/2025"),
    ("foro", "Foro", r"\bforo\b|comarca", "CPC art. 63 (Lei 14.879/2024)"),
]
