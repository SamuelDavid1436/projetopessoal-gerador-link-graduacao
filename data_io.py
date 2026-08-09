# -*- coding: utf-8 -*-
"""
data_io.py
==========
Funções para ler a lista de RAs (CSV ou Excel, apenas uma coluna) e para
gravar o resultado final, também em CSV e Excel.
"""
import csv as csv_modulo
import os
from datetime import datetime

import pandas as pd

import config


def _detectar_separador_csv(caminho_arquivo: str):
    """
    Detecta o separador de um .csv de forma confiável. NÃO usa o
    sep=None/engine='python' do pandas pra isso — foi descoberto que esse
    modo erra sozinho (trunca valores!) em arquivos com uma única coluna
    de números e sem cabeçalho, que é exatamente o formato mais comum de
    planilha de RAs. csv.Sniffer() é bem mais confiável pra esse caso.

    Devolve o separador detectado, ou None se não achar nenhum de forma
    confiável — nesse caso, quem chama deve tratar a linha inteira como
    um campo só (arquivo de uma coluna sem delimitador nenhum).
    """
    with open(caminho_arquivo, "r", encoding="utf-8-sig", errors="ignore") as f:
        amostra = f.read(4096)
    if not amostra.strip():
        return None
    try:
        dialeto = csv_modulo.Sniffer().sniff(amostra, delimiters=",;\t")
        return dialeto.delimiter
    except csv_modulo.Error:
        return None  # sem delimitador confiável -- provavelmente uma coluna só


def extrair_ras_com_erro(caminho_resultado_csv: str) -> list:
    """
    Lê um arquivo resultado.csv de uma execução já concluída e devolve
    só os RAs das linhas cujo "Status da Consulta" indica erro (começa
    com "Erro") — usado pelo botão "Reprocessar erros", pra montar uma
    nova base só com quem falhou, sem precisar filtrar a planilha na mão.
    """
    if not os.path.isfile(caminho_resultado_csv):
        return []
    try:
        df = pd.read_csv(caminho_resultado_csv, sep=";", dtype=str, encoding="utf-8-sig")
    except (OSError, pd.errors.ParserError):
        return []
    if "RA" not in df.columns or "Status da Consulta" not in df.columns:
        return []

    status = df["Status da Consulta"].fillna("").astype(str).str.strip().str.lower()
    mascara_erro = status.str.startswith("erro")
    ras_com_erro = df.loc[mascara_erro, "RA"].dropna().astype(str).tolist()
    return ras_com_erro


def salvar_lista_ras(ras: list, caminho_destino: str):
    """Salva uma lista simples de RAs num .csv (uma coluna, com cabeçalho
    'RA') — usado pra gerar a base de reprocessamento de erros. Sem BOM
    (utf-8 puro): com BOM, o cabeçalho "RA" vira "\\ufeffRA" e o filtro de
    cabeçalho de ler_lista_ras não reconhece mais como cabeçalho."""
    os.makedirs(os.path.dirname(caminho_destino), exist_ok=True)
    df = pd.DataFrame({"RA": ras})
    df.to_csv(caminho_destino, index=False, encoding="utf-8")


def ler_lista_ras(caminho_arquivo: str) -> list:
    """
    Lê um arquivo CSV ou Excel contendo uma única coluna de RAs (com ou sem
    cabeçalho) e devolve uma lista de strings (RAs), sem valores vazios.

    IMPORTANTE: não remove RAs repetidos — se o mesmo RA aparecer mais de
    uma vez no arquivo importado, ele é processado todas as vezes que
    aparecer. Isso é proposital: a mesma base pode ser rodada várias vezes
    por semana (gerando link atualizado pra quem ainda não pagou), e nada
    aqui trava ou pula RA repetido, nem entre execuções nem dentro do
    mesmo arquivo.
    """
    extensao = os.path.splitext(caminho_arquivo)[1].lower()

    if extensao == ".csv":
        separador = _detectar_separador_csv(caminho_arquivo)
        if separador is None:
            # sem delimitador confiável -- trata a linha inteira como um
            # campo só (caso mais comum: uma coluna de RAs, sem cabeçalho)
            df = pd.read_csv(caminho_arquivo, sep="\x00", engine="python", header=None, dtype=str)
        else:
            df = pd.read_csv(caminho_arquivo, sep=separador, engine="python", header=None, dtype=str)
    elif extensao in (".xlsx", ".xls"):
        df = pd.read_excel(caminho_arquivo, header=None, dtype=str)
    else:
        raise ValueError(
            f"Formato de arquivo não suportado: {extensao}. Use .csv, .xlsx ou .xls."
        )

    # pega a primeira coluna, remove vazios e possível cabeçalho textual
    primeira_coluna = df.iloc[:, 0].dropna().astype(str).str.strip()
    ras = [ra for ra in primeira_coluna.tolist() if ra and ra.upper() not in ("RA", "MATRICULA", "MATRÍCULA")]

    return ras


def salvar_resultado(registros: list, pasta_saida: str = None, momento: datetime = None) -> tuple:
    """
    Salva a lista de registros (lista de dicionários, chaves = config.COLUNAS_SAIDA)
    numa SUBPASTA própria dentro da pasta de saída, nomeada com a data/hora
    da importação (`momento` — normalmente o início da execução). Assim,
    cada vez que uma base é importada e processada, os arquivos ficam
    isolados na pasta daquela execução específica, sem se misturar com
    execuções anteriores ou seguintes.

    Exemplo: duas importações no mesmo dia geram duas pastas diferentes:
        saida/2026-07-20_14-42-05/resultado.csv
        saida/2026-07-20_14-42-05/resultado.xlsx
        saida/2026-07-20_15-00-12/resultado.csv
        saida/2026-07-20_15-00-12/resultado.xlsx

    Retorna (caminho_csv, caminho_xlsx).
    """
    pasta_saida = pasta_saida or config.PASTA_SAIDA
    momento = momento or datetime.now()

    nome_pasta_execucao = momento.strftime("%Y-%m-%d_%H-%M-%S")
    pasta_execucao = os.path.join(pasta_saida, nome_pasta_execucao)
    os.makedirs(pasta_execucao, exist_ok=True)

    df = pd.DataFrame(registros, columns=config.COLUNAS_SAIDA)

    caminho_csv = os.path.join(pasta_execucao, "resultado.csv")
    caminho_xlsx = os.path.join(pasta_execucao, "resultado.xlsx")

    df.to_csv(caminho_csv, index=False, encoding="utf-8-sig", sep=";")
    df.to_excel(caminho_xlsx, index=False)

    return caminho_csv, caminho_xlsx


# Sub-colunas de cada bloco de mês no relatório largo. "Situacao Mensalidade"
# substitui os antigos "Competencia"/"Ano" — como agora cada bloco já tem o
# nome do mês travado no cabeçalho (ex: "Junho - Valor Pago"), não precisa
# repetir mês/ano dentro do bloco; só indica se aquele mês existe ou não
# pra esse aluno.
_SUBCOLUNAS_POR_MES = ["Situacao Mensalidade", "Valor Pago", "Link Pagamento"]

# Ordem final do relatório: Situação (financeira) primeiro, depois um
# bloco fixo pra cada mês de config.MES_MINIMO_RELATORIO até
# config.MES_MAXIMO_RELATORIO, e só no final os dados de identificação do aluno.
_COLUNAS_FIXAS_INICIO = ["Situacao"]
_COLUNAS_FIXAS_FIM = ["RA", "Perfil", "CPF", "Nome", "Celular", "E-mail"]


def _meses_fixos_relatorio() -> list:
    """Lista travada de (mês, ano) — de config.MES_MINIMO_RELATORIO/
    ANO_MINIMO_RELATORIO até config.MES_MAXIMO_RELATORIO/ANO_MAXIMO_RELATORIO,
    inclusive nas duas pontas. Suporta virar o ano no meio (ex: Novembro/2026
    até Fevereiro/2027), caso um dia precise."""
    idx_ini = config.MESES.index(config.MES_MINIMO_RELATORIO)
    idx_fim = config.MESES.index(config.MES_MAXIMO_RELATORIO)
    ano_ini = int(config.ANO_MINIMO_RELATORIO)
    ano_fim = int(config.ANO_MAXIMO_RELATORIO)

    meses = []
    ano_atual, idx_atual = ano_ini, idx_ini
    while (ano_atual, idx_atual) <= (ano_fim, idx_fim):
        meses.append((config.MESES[idx_atual], str(ano_atual)))
        idx_atual += 1
        if idx_atual > 11:
            idx_atual = 0
            ano_atual += 1
    return meses


def salvar_relatorio_meses(resultados: list, pasta_saida: str = None, momento: datetime = None) -> tuple:
    """
    Gera um arquivo SEPARADO (relatorio_meses.csv/.xlsx) — não altera o
    resultado.csv/.xlsx normal — com as parcelas de cada aluno, em formato
    LARGO: uma linha por aluno, com um bloco de colunas TRAVADO (sempre o
    mesmo, independente do aluno) pra cada mês entre
    config.MES_MINIMO_RELATORIO/ANO_MINIMO_RELATORIO e
    config.MES_MAXIMO_RELATORIO/ANO_MAXIMO_RELATORIO (hoje: Junho a
    Dezembro/2026 — mude essas constantes em config.py quando precisar
    avançar o período).

    Cada bloco de mês tem 3 colunas, já nomeadas com o mês de verdade (ex:
    "Junho - Situacao Mensalidade", "Junho - Valor Pago", "Junho - Link
    Pagamento"):
      - Situacao Mensalidade: "Com mensalidade" se existir uma parcela
        daquele mês pra esse aluno, "Sem mensalidade" se não existir.
      - Valor Pago / Link Pagamento: vazios quando "Sem mensalidade".

    Cada mês em aberto (não Pago/Negociado) tem o link de pagamento
    gerado de verdade — vale pra todo mundo, pode ser mais de um link por
    aluno (ver crm_client.capturar_parcelas_a_partir_de).

    Ordem das colunas: Situação (financeira), Junho - ..., Julho - ...,
    ..., Dezembro - ..., e por último RA, Perfil, CPF, Nome, Celular,
    E-mail.

    `resultados` é a mesma lista de registros da execução — cada um deve
    ter a chave "_parcelas_relatorio" (lista de dicionários, uma por
    parcela, já filtrada/ordenada por crm_client.py). Salva na MESMA pasta
    da execução (mesmo `momento`) que o resultado.csv/.xlsx normal.

    Retorna (caminho_csv, caminho_xlsx).
    """
    pasta_saida = pasta_saida or config.PASTA_SAIDA
    momento = momento or datetime.now()

    nome_pasta_execucao = momento.strftime("%Y-%m-%d_%H-%M-%S")
    pasta_execucao = os.path.join(pasta_saida, nome_pasta_execucao)
    os.makedirs(pasta_execucao, exist_ok=True)

    meses_fixos = _meses_fixos_relatorio()  # [(mes, ano), ...] travado

    colunas_finais = list(_COLUNAS_FIXAS_INICIO)
    for mes, _ano in meses_fixos:
        for subcoluna in _SUBCOLUNAS_POR_MES:
            colunas_finais.append(f"{mes} - {subcoluna}")
    colunas_finais += _COLUNAS_FIXAS_FIM

    linhas = []
    for registro in resultados:
        linha = {coluna: registro.get(coluna, "") for coluna in _COLUNAS_FIXAS_INICIO + _COLUNAS_FIXAS_FIM}
        parcelas = registro.get("_parcelas_relatorio", []) or []
        # indexa as parcelas desse aluno por (mês, ano) pra achar rápido
        parcelas_por_mes = {(p.get("Competencia"), str(p.get("Ano"))): p for p in parcelas}

        algum_mes_preenchido = False
        for mes, ano in meses_fixos:
            dados_mes = parcelas_por_mes.get((mes, ano))
            if dados_mes is not None:
                linha[f"{mes} - Situacao Mensalidade"] = "Com mensalidade"
                linha[f"{mes} - Valor Pago"] = dados_mes.get("Valor Pago", "")
                linha[f"{mes} - Link Pagamento"] = dados_mes.get("Link Pagamento", "")
                algum_mes_preenchido = True
            else:
                linha[f"{mes} - Situacao Mensalidade"] = "Sem mensalidade"
                linha[f"{mes} - Valor Pago"] = ""
                linha[f"{mes} - Link Pagamento"] = ""

        # Linha toda vazia (sem Situação nem nenhum mês encontrado) --
        # sinaliza o motivo em vez de deixar tudo em branco sem explicação
        # nenhuma. Usa o texto exato "RA não encontrado na base" quando é
        # isso mesmo que aconteceu; se ficou vazia por outro motivo de
        # erro (timeout esgotado, sessão do navegador morta, etc), mostra
        # esse motivo real em vez de inventar "não encontrado" à toa.
        sem_situacao = not str(linha.get("Situacao", "")).strip()
        if sem_situacao and not algum_mes_preenchido:
            status_consulta = str(registro.get("Status da Consulta", "") or "")
            eh_outro_erro = (
                status_consulta.lower().startswith("erro")
                and "não encontrado" not in status_consulta.lower()
            )
            if eh_outro_erro:
                linha["Situacao"] = f"Erro na consulta: {status_consulta[len('Erro:'):].strip()}"
            else:
                linha["Situacao"] = "RA não encontrado na base"

        linhas.append(linha)

    df = pd.DataFrame(linhas, columns=colunas_finais)

    caminho_csv = os.path.join(pasta_execucao, "relatorio_meses.csv")
    caminho_xlsx = os.path.join(pasta_execucao, "relatorio_meses.xlsx")

    df.to_csv(caminho_csv, index=False, encoding="utf-8-sig", sep=";")
    df.to_excel(caminho_xlsx, index=False)

    return caminho_csv, caminho_xlsx