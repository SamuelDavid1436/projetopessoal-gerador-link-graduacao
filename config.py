# -*- coding: utf-8 -*-
"""
config.py
=========
Todas as configurações "ajustáveis" do projeto ficam aqui, separadas da lógica,
para que você (ou quem for dar manutenção) não precise mexer no restante do
código para pequenos ajustes.

IMPORTANTE — LEIA ANTES DE RODAR:
Alguns seletores abaixo foram estimados a partir do HTML que você enviou.
O HTML da aba "Cadastro" (CPF, Nome, Sobrenome, Celular, E-mail, Curso) não
veio no briefing — só a lista de abas. Também a grade "Financeiro" tem 21
colunas ao todo, mas só 10 apareceram no HTML (Parcela, Competência, Ano,
Número de Documento, Data Emissão, Liberação meio pgto, Valor Atualizado,
Valor c/ Desc. Pont., Data de Vencimento). Faltam os col-id reais de:
"Data pagamento", "Valor Pago", "Meio de pagamento", "Status da fatura"
e "Origem".

Marquei esses pontos abaixo com "# TODO-CONFIRMAR". Para descobrir o valor
certo: abra a página no Chrome, tecla F12 (DevTools), clique com o botão
direito na coluna/campo desejado > Inspecionar, e procure o atributo
col-id="..." (na grade) ou data-id="...-FieldSectionItemContainer" (no
formulário). Copie o valor e cole aqui.
"""

# ---------------------------------------------------------------------------
# URL da página inicial (lista de alunos / matrículas)
# ---------------------------------------------------------------------------
URL_LISTA_ALUNOS = (
    "https://kroton.crm2.dynamics.com/main.aspx?appid=b1472c17-f92a-ee11-bdf5-"
    "000d3a88da6e&pagetype=entitylist&etn=mshied_academicperioddetails&"
    "viewid=d71d14af-e34e-f111-bec7-7ced8da7d70c&viewType=4230"
)

# ---------------------------------------------------------------------------
# Pasta onde fica o "perfil" persistente do Chrome (mantém o login salvo
# entre execuções). Cada janela paralela usa uma cópia deste perfil.
# ---------------------------------------------------------------------------
import os


def _descobrir_pasta_documentos() -> str:
    """
    Tenta usar a pasta Documentos do usuário. Em algumas máquinas (comum com
    OneDrive redirecionando a pasta Documentos) essa pasta não existe ou não
    pode ser criada normalmente pelo Python — nesse caso, cai para uma pasta
    "CapturaLinkPagamento_Dados" ao lado do próprio programa, que sempre
    funciona.
    """
    candidata = os.path.join(os.path.expanduser("~"), "Documents", "CapturaLinkPagamento")
    try:
        os.makedirs(candidata, exist_ok=True)
        return candidata
    except OSError:
        pasta_do_programa = os.path.dirname(os.path.abspath(__file__))
        alternativa = os.path.join(pasta_do_programa, "CapturaLinkPagamento_Dados")
        os.makedirs(alternativa, exist_ok=True)
        return alternativa


def _descobrir_pasta_local_app() -> str:
    """
    Pasta pra dados "vivos" que mudam o tempo todo — hoje só os perfis do
    Chrome — de propósito FORA do OneDrive/Documentos. Um perfil de
    navegador é basicamente um banco de dados sendo escrito a cada poucos
    segundos; se ficar numa pasta sincronizada (OneDrive, Google Drive
    etc), o sincronizador disputando os mesmos arquivos com o Chrome causa
    exatamente os travamentos/corrupção de perfil vistos na prática
    ("Chrome failed to start: crashed", sessão perdida do nada, perfil
    corrompido). %LOCALAPPDATA% nunca é sincronizado por padrão — é
    literalmente pra esse tipo de dado que ele existe.
    """
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    candidata = os.path.join(base, "CapturaLinkPagamento")
    try:
        os.makedirs(candidata, exist_ok=True)
        return candidata
    except OSError:
        pasta_do_programa = os.path.dirname(os.path.abspath(__file__))
        alternativa = os.path.join(pasta_do_programa, "CapturaLinkPagamento_Perfis")
        os.makedirs(alternativa, exist_ok=True)
        return alternativa


PASTA_DOCUMENTOS = _descobrir_pasta_documentos()
PASTA_SAIDA = os.path.join(PASTA_DOCUMENTOS, "saida")
PASTA_LOGS = os.path.join(PASTA_DOCUMENTOS, "logs")

PASTA_APP_LOCAL = _descobrir_pasta_local_app()
PASTA_SCREENSHOTS = os.path.join(PASTA_LOGS, "screenshots")  # 1 print por erro

# Log temporário só pra permitir retomar em caso de queda/travamento da
# automação NO MEIO de uma execução (não é histórico permanente — é
# descartado assim que a execução termina normalmente, e também é
# descartado/reiniciado sempre que uma NOVA importação é iniciada).
ARQUIVO_RETOMADA = os.path.join(PASTA_LOGS, "execucao_em_andamento.json")


# ---------------------------------------------------------------------------
# Paleta de cores / identidade visual
# ---------------------------------------------------------------------------
COR_VERDE = "#1F9D55"          # 30% - cor de marca (navegação, cabeçalhos, ícones)
COR_VERDE_ESCURO = "#15703D"   # hover/variação escura do verde
COR_DOURADO = "#F2B705"        # 10% - destaque/chamada para ação (botões principais)
COR_DOURADO_ESCURO = "#C99404"  # hover do dourado
COR_CREME = "#FEF8F1"          # 60% - fundo claro
COR_CINZA_ESCURO = "#525252"
COR_GELO = "#FCFAF9"           # 60% - fundo claro (variação)

NOME_PRODUTO = "Captura Link de Pagamento"

# ---------------------------------------------------------------------------
# Meses (usados no seletor "mês/ano de referência")
# ---------------------------------------------------------------------------
MESES = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]

# Relatório separado (ver data_io.salvar_relatorio_meses): as colunas são
# TRAVADAS (fixas) entre esse mês/ano mínimo e o máximo — sempre a mesma
# quantidade de blocos de coluna no arquivo, independente do aluno. Mude
# aqui quando precisar avançar o período (ex: virou o ano, agora é de
# Janeiro a Dezembro/2027).
MES_MINIMO_RELATORIO = "Junho"
ANO_MINIMO_RELATORIO = "2026"
MES_MAXIMO_RELATORIO = "Dezembro"
ANO_MAXIMO_RELATORIO = "2026"

# ---------------------------------------------------------------------------
# Seletores — Página de LISTA (busca por RA)
# ---------------------------------------------------------------------------
SELETOR_CAMPO_BUSCA = "input[id^='quickFind_text_']"
SELETOR_LINHA_RESULTADO = "div.ag-center-cols-container div[role='row']"
SELETOR_LINK_ABRIR_REGISTRO = "div[col-id='mshied_name'] a"

# O "Curso" só existe como coluna nesta grade de busca (Controle Alunos) —
# não existe na aba Cadastro do registro do aluno. Por isso é capturado
# ANTES do duplo clique que abre o registro (ver abrir_registro_do_resultado
# em crm_client.py).
COL_CURSO_LISTA = "mshied_programid"

# ---------------------------------------------------------------------------
# Seletores — abas do formulário do aluno
# ---------------------------------------------------------------------------
XPATH_ABA_CADASTRO = "//li[@title='Cadastro']"
XPATH_ABA_FINANCEIRO = "//li[@title='Financeiro']"

# ---------------------------------------------------------------------------
# Grade "Todos os Extratos" (aba Financeiro) — escopado pelo aria-label para
# não pegar linhas de nenhuma outra grid que exista na mesma tela.
# ---------------------------------------------------------------------------
SELETOR_GRID_EXTRATOS = "div.ag-root[aria-label='Todos os Extratos']"
SELETOR_LINHAS_EXTRATOS = f"{SELETOR_GRID_EXTRATOS} div.ag-center-cols-container div[role='row']"

# ---------------------------------------------------------------------------
# Mapeamento de campos da aba "Cadastro"
# Padrão de seletor usado (visto na seção "Status Financeiro" do HTML):
#   div[data-id='<nome_logico>-FieldSectionItemContainer'] input
# Os nomes lógicos abaixo são ESTIMATIVAS (padrão comum Dynamics / mshied).
# TODO-CONFIRMAR: valide cada um inspecionando a aba Cadastro real.
# ("curso" foi removido daqui — não existe nessa aba, ver COL_CURSO_LISTA acima)
# ---------------------------------------------------------------------------
CAMPOS_CADASTRO = {
    "cpf": "kcs_cpf",                # TODO-CONFIRMAR
    "nome": "firstname",             # TODO-CONFIRMAR
    "sobrenome": "lastname",         # TODO-CONFIRMAR
    "celular": "mobilephone",        # confirmado via coluna da grade de alunos
    "email": "emailaddress1",        # TODO-CONFIRMAR
}


# ---------------------------------------------------------------------------
# Mapeamento de campos da seção "Status Financeiro" (aba Financeiro)
# Só a Situação (Inadimplente/Adimplente) é usada — o campo "Status
# Financeiro" (Ativo/etc.) foi removido a pedido, não é mais consultado.
# ---------------------------------------------------------------------------
CAMPOS_STATUS_FINANCEIRO = {
    "situacao": "kcs_situacao",              # Inadimplente / Adimplente
}

# ---------------------------------------------------------------------------
# Colunas da grade "Todos os Extratos" (aba Financeiro)
# col-id confirmados no HTML enviado:
# ---------------------------------------------------------------------------
COL_PARCELA = "kcs_numeroparcela"
COL_COMPETENCIA = "kcs_mesreferencia"
COL_ANO = "kcs_ano"
COL_NUMERO_DOCUMENTO = "kcs_numerofatura"
COL_DATA_EMISSAO = "kcs_dataemissao"
COL_LIBERACAO_MEIO_PGTO = "kcs_datainsercaofatura"
COL_VALOR_ATUALIZADO = "kcs_valor"              # "Valor Atualizado"
COL_VALOR_DESC_PONTUALIDADE = "kcs_valoratualizado"  # "Valor c/ Desc. Pont."
COL_DATA_VENCIMENTO = "kcs_vencimento"

# Colunas citadas no briefing mas SEM col-id confirmado no HTML enviado
# (a grade tem 21 colunas, só vimos ~15 em telas/HTML). Preencha o col-id
# real assim que conseguir inspecionar a tela (veja o aviso completo logo
# abaixo), ou a automação vai deixar essas colunas em branco no resultado.
COL_DATA_PAGAMENTO = "kcs_datapagamento"     # "Data pagamento" — confirmado
COL_VALOR_PAGO = "kcs_valorpago"             # "Valor Pago" — confirmado
COL_MEIO_PAGAMENTO = "kcs_meiopagamento"     # "Meio de pagamento" — confirmado
COL_STATUS_FATURA = "kcs_status"             # "Status da fatura" — confirmado
COL_ORIGEM = "kcs_tipofatura"                # "Origem" — confirmado
COL_TIPO = "kcs_tipo"                        # "Tipo" — confirmado (HTML completo da grade)
COL_EM_CONTESTACAO = "kcs_emcontestacao"     # "Em Contestação" — confirmado (HTML completo da grade)
# "Motivo do Bloqueio" / "Data Início Bloqueio" / "Data Fim Bloqueio" —
# aparecem na tela mas ainda SEM col-id confirmado. Se precisar deles no
# relatório de meses, inspecione uma célula dessas colunas (botão direito
# > Inspecionar) e me manda o col-id, igual fez com as outras.
# IMPORTANTE: NÃO dá pra "adivinhar" esses col-id pelo padrão dos outros —
# já vimos neste mesmo CRM casos em que o nome lógico e o rótulo da coluna
# não batem (ex: col-id "kcs_valor" = rótulo "Valor Atualizado", e
# "kcs_valoratualizado" = rótulo "Valor c/ Desc. Pont."). Values errados
# nesses TODO poderiam gravar dado errado na coluna errada, então prefiro
# deixar em branco a arriscar. Para descobrir o valor certo: no navegador,
# botão direito na coluna > Inspecionar > procure o atributo col-id="...".
#
# A automação NÃO depende mais desses campos para decidir se gera o link:
# agora ela sempre tenta gerar e deixa o próprio CRM responder (ver
# gerar_link_pagamento em crm_client.py). Esses COL_* são usados só pra
# preencher as colunas informativas no arquivo de saída, quando disponíveis.

VALOR_STATUS_FATURA_PAGO = "Pago"  # mantido para uso informativo futuro

# Status da Fatura que NÃO precisam de link de pagamento — a automação só
# traz as informações da grade e passa pro próximo RA, sem clicar em nada.
STATUS_FATURA_SEM_LINK = ["pago", "negociado"]

# ---------------------------------------------------------------------------
# Botão "Meio de Pagamento" (abre modal com o link de pagamento)
# O id completo tem um número que muda por sessão (...-8661-button), então
# usamos um seletor mais estável baseado no texto/aria-label.
# ---------------------------------------------------------------------------
XPATH_BOTAO_MEIO_PAGAMENTO = "//button[@aria-label='Download PDF' and contains(@data-lp-id, 'MeioPagamento')]"

# ---------------------------------------------------------------------------
# Modal "Link do Meio de Pagamento"
# ---------------------------------------------------------------------------
SELETOR_MODAL_TITULO = "h1[aria-label='Link do Meio de Pagamento']"
SELETOR_MODAL_TEXTO_LINK = "span[data-id='dialogMessageText']"
SELETOR_MODAL_BOTAO_FECHAR = "button[data-id='dialogCloseIconButton']"

# ---------------------------------------------------------------------------
# Colunas do arquivo de saída (CSV e Excel) — ordem final
# ---------------------------------------------------------------------------
COLUNAS_SAIDA = [
    "RA",
    "Perfil",                 # qual dos perfis (janela) consultou esse RA
    "CPF",
    "Nome",
    "Celular",
    "E-mail",
    "Curso",
    "Situacao",              # Inadimplente / Adimplente
    "Mensalidade Encontrada",  # Sim / Não (para o mês/ano pesquisado)
    "Competencia",
    "Ano",
    "Valor Atualizado",
    "Data Pagamento",
    "Valor Pago",
    "Meio de Pagamento",
    "Status da Fatura",
    "Origem",
    "Link de Pagamento",
    "Data/Hora do Link",     # quando o link foi gerado (só preenchido quando gera de verdade)
    # SUCESSO_COM_MENSALIDADE / SEM_MENSALIDADE / SEM_EXTRATOS / ERRO_CARREGAMENTO /
    # ERRO_CONSULTA / TIMEOUT_ATHENAS -- SEM_MENSALIDADE só quando a tela
    # carregou e confirmou que não há mensalidade (ver crm_client.py)
    "Resultado da Consulta",
    "Status da Consulta",    # OK / Erro: <mensagem>
]

# Tempo máximo de espera (segundos) por elemento na página
TIMEOUT_PADRAO = 22

# Timeout curto usado só pra "a grade financeira terminou de carregar as
# linhas" — não precisa ser o mesmo tempo do timeout geral. Isso evita
# ficar esperando 20-30s quando a fatura simplesmente não existe (ex: mês
# seguinte ainda não faturado, que é o caso mais comum).
TIMEOUT_ESTABILIZACAO_GRID = 5

# Zoom (em %) aplicado na tela ao entrar na aba Financeiro, pra fazer a
# grade "Todos os Extratos" (que é bem larga — 21 colunas) caber inteira
# na tela sem precisar rolar horizontalmente. Isso evita todo o problema de
# colunas "virtualizadas" (removidas do HTML por estarem fora da área
# visível) que causava campos vindo em branco. Se ainda faltar alguma
# coluna depois disso, é só diminuir esse número (ex: 55).
ZOOM_GRADE_FINANCEIRO = 60

# Proteção contra instabilidade do Athenas na tela de mensalidade (aba
# Financeiro). Se a grade "Todos os Extratos" não carregar em
# TIMEOUT_CARREGAMENTO_FINANCEIRO segundos, a automação dá refresh (F5) na
# página do aluno e espera de novo, até MAX_TENTATIVAS_REFRESH_FINANCEIRO
# vezes. Esgotadas as tentativas, o RA sai como ERRO_CARREGAMENTO (nunca
# como "sem mensalidade") e entra no "Reprocessar erros".
TIMEOUT_CARREGAMENTO_FINANCEIRO = 30
MAX_TENTATIVAS_REFRESH_FINANCEIRO = 3
# Quando a grade vem VAZIA (nenhum extrato), quantas vezes dar refresh e
# conferir de novo antes de aceitar o vazio como real (SEM_EXTRATOS).
CONFIRMACOES_GRADE_VAZIA = 1

# Antes de gravar SEM_MENSALIDADE (grade com linhas, mas sem o mês), dá um
# refresh e procura de novo. Custa um recarregamento só nesses RAs.
CONFIRMAR_SEM_MENSALIDADE = True

# Depois de clicar em "Meio de Pagamento", o modal mostra "Gerando link..."
# por um tempo antes do link aparecer. Quanto esperar (segundos) esse texto
# virar o link (ou a recusa do CRM) antes de desistir e tentar o RA de novo.
TIMEOUT_GERACAO_LINK = 90

# ---------------------------------------------------------------------------
# Histórico de execuções (usado no dashboard/página de Execuções)
# ---------------------------------------------------------------------------
ARQUIVO_HISTORICO = os.path.join(PASTA_LOGS, "historico_execucoes.json")

VERSAO_APP = "1.1.0"

# ---------------------------------------------------------------------------
# Ícone, logo e manual do aplicativo (pasta assets/, ao lado deste arquivo)
# Usa sys._MEIPASS quando empacotado com PyInstaller (.exe), senão a pasta
# deste próprio arquivo — assim os caminhos funcionam tanto rodando com
# "python main.py" quanto num .exe empacotado no futuro.
# ---------------------------------------------------------------------------
import sys

PASTA_PROJETO = os.path.dirname(os.path.abspath(__file__))


def caminho_recurso(*partes) -> str:
    base = getattr(sys, "_MEIPASS", PASTA_PROJETO)
    return os.path.join(base, *partes)


CAMINHO_ICONE = caminho_recurso("assets", "icone.ico")
CAMINHO_LOGO = caminho_recurso("assets", "logo.png")
CAMINHO_MANUAL = caminho_recurso("assets", "manual.pdf")
CAMINHO_MANUAL_WORD = caminho_recurso("assets", "manual.docx")  # cópia editável, se precisar

# ---------------------------------------------------------------------------
# Perfis (até 3 logins independentes do Chrome, cada um com apelido próprio)
# ---------------------------------------------------------------------------
NUM_PERFIS = 3
PASTA_PERFIS = os.path.join(PASTA_APP_LOCAL, "perfis")
ARQUIVO_PERFIS_META = os.path.join(PASTA_APP_LOCAL, "perfis_meta.json")