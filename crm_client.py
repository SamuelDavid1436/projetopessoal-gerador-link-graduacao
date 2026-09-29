# -*- coding: utf-8 -*-
"""
crm_client.py
=============
Encapsula toda a interação com o navegador (Selenium) para uma única
instância/janela. Cada worker paralelo cria seu próprio CrmClient com seu
próprio WebDriver.

IMPORTANTE: toda interação (clique/digitação) passa pelos helpers
`_clicar()` / `_digitar()`, que esperam o elemento ficar de fato visível e
habilitado (não só presente no DOM) antes de agir, e têm um fallback via
JavaScript se o Selenium ainda assim disser "not interactable" (comum em
grids virtualizados como o ag-Grid, onde o elemento existe no DOM mas está
fora da área visível/rolada).
"""
import os
import re
import time
from datetime import datetime

from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import config


class ErroConsultaRA(Exception):
    """Erro esperado durante a consulta de um RA (para não derrubar o processo todo)."""


class ErroDocumentoIndisponivel(ErroConsultaRA):
    """O CRM respondeu, mas recusou gerar o link/documento (ex: fatura já paga).
    Não é uma falha da automação — é tratado como um resultado válido."""


class ErroCarregamentoAthenas(ErroConsultaRA):
    """A tela de mensalidade (aba Financeiro / grade 'Todos os Extratos') não
    terminou de carregar, mesmo depois das tentativas de refresh. NUNCA pode
    ser tratado como "sem mensalidade": a consulta simplesmente não aconteceu."""

    def __init__(self, mensagem: str, tentativas: int = 0):
        super().__init__(mensagem)
        self.tentativas = tentativas


class ErroRespostaAthenas(ErroConsultaRA):
    """O CRM não respondeu a uma ação (ex: clique em 'Meio de Pagamento' sem
    nenhum modal). É instabilidade do sistema de origem: o RA inteiro deve
    ser tentado de novo (ver runner.py), não registrado como erro definitivo."""


# Classificação final de cada RA (coluna "Resultado da Consulta" da saída).
# "Consultei e não existe mensalidade" (SEM_MENSALIDADE) e "não consegui
# consultar" (ERRO_*/TIMEOUT_*) NUNCA podem ter o mesmo código.
RESULTADO_SUCESSO_COM_MENSALIDADE = "SUCESSO_COM_MENSALIDADE"
RESULTADO_SEM_MENSALIDADE = "SEM_MENSALIDADE"
# grade "Todos os Extratos" totalmente vazia no CRM, confirmada com refresh
# -- não é "sem mensalidade do mês": é caso pra conferir manualmente
RESULTADO_SEM_EXTRATOS = "SEM_EXTRATOS"
RESULTADO_ERRO_CARREGAMENTO = "ERRO_CARREGAMENTO"
RESULTADO_ERRO_CONSULTA = "ERRO_CONSULTA"
RESULTADO_TIMEOUT_ATHENAS = "TIMEOUT_ATHENAS"


class CrmClient:
    def __init__(self, driver, timeout: int = config.TIMEOUT_PADRAO, log=print):
        self.driver = driver
        self.timeout = timeout
        self._log_externo = log
        self._ra_atual = ""
        self.wait = WebDriverWait(driver, timeout)
        # quando True, a próxima chamada a abrir_lista_alunos() força um
        # reload completo da página, mesmo que já pareça estar na lista —
        # usado depois de qualquer erro (ex: "RA não localizado"), pra
        # garantir que o campo de busca comece limpo de verdade no próximo
        # RA, em vez de arriscar ficar concatenando texto num campo velho.
        self._forcar_reload_lista = False
        # quando True, o navegador/sessão morreu de vez (travou, fechou,
        # ficou sem memória etc.) — quem chama consultar_ra (runner.py)
        # precisa checar essa flag depois de CADA RA e reiniciar o
        # navegador se ela vier True. Sem isso, todo RA seguinte falha com
        # o mesmo erro, um atrás do outro, até acabar a lista inteira.
        self.sessao_morta = False

    # Textos que aparecem quando o Chrome/ChromeDriver morreu de vez (não é
    # um erro de UMA tela específica — é a sessão inteira que já era).
    _ASSINATURAS_SESSAO_MORTA = (
        "invalid session id",
        "chrome not reachable",
        "session deleted",
        "disconnected: not connected to devtools",
        "target window already closed",
        "no such window",
        "unable to receive message from renderer",
        "connection refused",
        "chrome failed to start",
    )

    def log(self, mensagem: str):
        """Log com o RA em consulta no começo de cada linha — com várias
        janelas rodando ao mesmo tempo, as linhas se misturam e sem isso não
        dá pra saber de qual RA é cada mensagem."""
        prefixo = f"[RA {self._ra_atual}] " if self._ra_atual else ""
        self._log_externo(f"{prefixo}{str(mensagem).strip()}")

    def _e_erro_de_sessao_morta(self, erro) -> bool:
        texto = str(erro).lower()
        return any(assinatura in texto for assinatura in self._ASSINATURAS_SESSAO_MORTA)

    # ------------------------------------------------------------------
    # Helpers de interação segura (esperar ficar interagível + fallback JS)
    # ------------------------------------------------------------------
    def _pronto_para_interagir(self, elemento) -> bool:
        try:
            return elemento.is_displayed() and elemento.is_enabled()
        except StaleElementReferenceException:
            return False

    def _esperar_pronto(self, elemento, timeout: float = 10):
        """Espera até o elemento estar visível e habilitado (não só presente no DOM)."""
        inicio = time.time()
        fim = inicio + timeout
        while time.time() < fim:
            if self._pronto_para_interagir(elemento):
                duracao = time.time() - inicio
                if duracao > 0.5:
                    self.log(f"  [debug] esperou {duracao:.1f}s pro elemento ficar pronto pra clicar")
                return elemento
            time.sleep(0.15)
        self.log(f"  [debug] elemento não ficou 'pronto' em {timeout}s — tentando clicar mesmo assim")
        return elemento  # segue mesmo assim; o clique/digitação abaixo tem fallback

    def _rolar_ate(self, elemento):
        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center', inline: 'center'});", elemento
            )
        except Exception:  # pylint: disable=broad-except
            pass

    def _clicar(self, elemento):
        """Clica com segurança: rola até o elemento, espera ficar interagível,
        tenta clique nativo e cai para clique via JS se necessário.

        IMPORTANTE: o teto de espera aqui é curto (2s) de propósito. Um
        elemento que já existe no DOM (achado por um find_element/CSS que
        deu certo) quase sempre já está clicável também — esperar muito
        tempo aqui só atrasa a automação à toa nos casos em que o elemento
        nunca vai ficar "pronto" por algum motivo bobo (ex: um instante de
        reflow do navegador depois do zoom). Se realmente não der certo, o
        fallback via JavaScript abaixo resolve a maioria dos casos mesmo
        assim, e quem chama essa função (ex: marcar_checkbox_linha) já tem
        sua própria lógica de repetir com uma referência nova.
        """
        self._rolar_ate(elemento)
        self._esperar_pronto(elemento, timeout=2)
        try:
            elemento.click()
            return
        except (ElementClickInterceptedException, ElementNotInteractableException, StaleElementReferenceException):
            pass
        try:
            self.driver.execute_script("arguments[0].click();", elemento)
        except Exception as erro:  # pylint: disable=broad-except
            raise ErroConsultaRA(f"Não consegui clicar no elemento mesmo com fallback: {erro}")

    def _digitar(self, elemento, texto: str):
        """Digita com segurança: rola até o campo, espera ficar interagível,
        tenta digitação nativa e cai para preenchimento via JS se necessário."""
        self._rolar_ate(elemento)
        self._esperar_pronto(elemento, timeout=2)
        try:
            elemento.click()
            elemento.clear()
            elemento.send_keys(texto)
            return
        except (ElementNotInteractableException, StaleElementReferenceException):
            pass
        # fallback: preenche via JS disparando o evento 'input' (necessário para
        # componentes controlados em React/Fluent UI, como os do Dynamics)
        try:
            self.driver.execute_script(
                """
                const el = arguments[0];
                const valor = arguments[1];
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                setter.call(el, valor);
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                """,
                elemento, texto,
            )
        except Exception as erro:  # pylint: disable=broad-except
            raise ErroConsultaRA(f"Não consegui digitar no campo mesmo com fallback: {erro}")

    # ------------------------------------------------------------------
    # Navegação básica
    # ------------------------------------------------------------------
    def abrir_lista_alunos(self):
        # se algum erro anterior pediu um reload forçado (ver
        # _forcar_reload_lista), ignora a otimização abaixo e recarrega
        # de verdade — garante que o campo de busca comece limpo.
        if self._forcar_reload_lista:
            self._forcar_reload_lista = False
            self.driver.get(config.URL_LISTA_ALUNOS)
            return

        # se já estiver nessa mesma tela de lista (ex: logo depois de abrir
        # o navegador pra capturar o e-mail do perfil), não precisa
        # recarregar — economiza um carregamento completo por janela.
        # IMPORTANTE: compara por marcadores específicos da URL de lista
        # (pagetype=entitylist), não só o começo do endereço — todas as
        # telas do CRM (lista, registro do aluno etc.) usam o mesmo
        # "main.aspx" como base, só o que muda é a query string.
        try:
            url_atual = self.driver.current_url
            ja_na_lista = "pagetype=entitylist" in url_atual and "etn=mshied_academicperioddetails" in url_atual
        except WebDriverException:
            ja_na_lista = False
        if ja_na_lista:
            return
        self.driver.get(config.URL_LISTA_ALUNOS)

    def buscar_ra(self, ra: str):
        """Digita o RA no campo de busca rápida e pressiona Enter."""
        campo = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, config.SELETOR_CAMPO_BUSCA))
        )
        self._digitar(campo, ra)
        campo.send_keys(Keys.ENTER)
        self._aguardar_resultado_busca()

    def _ha_mensagem_sem_resultados(self) -> bool:
        """
        Confere se a tela já está mostrando 'Não encontramos nada para
        mostrar aqui' (ou variações parecidas) — sinal rápido e direto de
        que o RA não existe, sem precisar esperar o timeout inteiro até
        desistir de achar uma linha que nunca vai aparecer.
        """
        try:
            elementos = self.driver.find_elements(
                By.XPATH,
                "//*[contains(normalize-space(.), 'Não encontramos nada') "
                "or contains(normalize-space(.), 'Nenhum registro encontrado') "
                "or contains(normalize-space(.), 'No records to show')]"
            )
            return len(elementos) > 0
        except WebDriverException:
            return False

    def _aguardar_resultado_busca(self, timeout: float = None):
        """
        Espera a grade de resultados terminar de recarregar depois do Enter.
        Em vez de um sleep fixo, espera até o texto da primeira linha ficar
        estável (não mudar) entre duas leituras seguidas — evita pegar a
        linha ainda em estado de "carregando" (shimmer). Se aparecer a
        mensagem de "sem resultados", sai na hora — não tem sentido ficar
        esperando uma linha que nunca vai chegar.
        """
        timeout = timeout or self.timeout
        fim = time.time() + timeout
        texto_anterior = None
        estavel_desde = None

        while time.time() < fim:
            linhas = self.driver.find_elements(By.CSS_SELECTOR, config.SELETOR_LINHA_RESULTADO)
            if not linhas:
                if self._ha_mensagem_sem_resultados():
                    return  # RA não existe -- sai rápido, sem esperar o timeout inteiro
                time.sleep(0.2)
                continue
            try:
                texto_atual = linhas[0].text.strip()
            except StaleElementReferenceException:
                texto_atual = ""

            if texto_atual and texto_atual == texto_anterior:
                if estavel_desde is None:
                    estavel_desde = time.time()
                elif time.time() - estavel_desde > 0.25:
                    return  # texto ficou igual por um tempinho: carregamento terminou
            else:
                estavel_desde = None

            texto_anterior = texto_atual
            time.sleep(0.2)
        # não travou em erro aqui — deixa abrir_registro_do_resultado() lidar
        # com "nenhum resultado" ou linha ainda instável

    def abrir_registro_do_resultado(self, ra: str) -> str:
        """
        Espera a linha de resultado aparecer, captura o "Curso" (só existe
        nessa grade de busca — Controle Alunos —, não na aba Cadastro do
        registro) e dá duplo clique para abrir o registro do aluno.
        Devolve o texto do Curso capturado (pode vir vazio).
        Lança ErroConsultaRA se nenhum resultado for encontrado.
        """
        # checagem rápida primeiro: se a mensagem de "sem resultados" já
        # está na tela, nem entra na espera longa — sai na hora
        if self._ha_mensagem_sem_resultados():
            self._forcar_reload_lista = True
            raise ErroConsultaRA(f"RA não encontrado no CRM Dynamics ({ra}).")

        try:
            linha = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, config.SELETOR_LINHA_RESULTADO))
            )
        except TimeoutException:
            # RA não encontrado ("Não encontramos nada para mostrar aqui").
            # Marca pra próxima busca recarregar a página de verdade — sem
            # isso, o campo de busca pode ficar "sujo" (texto de buscas
            # anteriores não limpo direito) e travar as próximas pesquisas.
            self._forcar_reload_lista = True
            raise ErroConsultaRA(f"RA não encontrado no CRM Dynamics ({ra}).")

        curso = ""
        fim_curso = time.time() + 1.5
        while time.time() < fim_curso:
            try:
                curso = linha.find_element(
                    By.CSS_SELECTOR, f"div[col-id='{config.COL_CURSO_LISTA}']"
                ).text.strip()
            except (NoSuchElementException, StaleElementReferenceException):
                curso = ""
            if curso:
                break
            time.sleep(0.2)

        try:
            link = linha.find_element(By.CSS_SELECTOR, config.SELETOR_LINK_ABRIR_REGISTRO)
            alvo = link
        except NoSuchElementException:
            alvo = linha

        self._rolar_ate(alvo)
        self._esperar_pronto(alvo, timeout=2)
        try:
            ActionChains(self.driver).double_click(alvo).perform()
        except (ElementNotInteractableException, ElementClickInterceptedException, StaleElementReferenceException):
            # fallback: dispara o duplo-clique via JS diretamente no elemento
            self.driver.execute_script(
                "arguments[0].dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));", alvo
            )

        time.sleep(1.2)
        return curso

    # ------------------------------------------------------------------
    # Abas do formulário
    # ------------------------------------------------------------------
    def clicar_aba(self, xpath: str, nome_aba: str):
        try:
            aba = self.wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        except TimeoutException:
            raise ErroConsultaRA(f"Não encontrei a aba '{nome_aba}' no registro do aluno.")
        self._clicar(aba)
        time.sleep(0.6)

    def ir_para_cadastro(self):
        self.clicar_aba(config.XPATH_ABA_CADASTRO, "Cadastro")
        self._definir_zoom(100)  # volta ao normal fora da aba Financeiro

    def ir_para_financeiro(self):
        self.clicar_aba(config.XPATH_ABA_FINANCEIRO, "Financeiro")
        # reduz o zoom pra a grade "Todos os Extratos" (21 colunas, bem
        # larga) caber inteira na tela sem precisar rolar horizontalmente —
        # evita o problema de colunas virtualizadas/removidas do DOM
        self._definir_zoom(config.ZOOM_GRADE_FINANCEIRO)
        self._aguardar_financeiro_pronto()

    def _aguardar_financeiro_pronto(self, timeout: float = 6):
        """
        Espera a aba Financeiro ter ALGO pronto pra ler antes de tentar
        extrair qualquer informação dela — em vez de um sleep fixo "no
        escuro" (que ou espera mais do que precisa em sistema rápido, ou
        espera de menos e dá erro falso em sistema/internet lento), espera
        até aparecer o campo Situação OU a grade de extratos, o que vier
        primeiro. As esperas específicas de cada campo (_ler_campo) e da
        grade (localizar_parcela) continuam existindo por cima disso —
        essa aqui é só o primeiro "sinal de vida" da aba.
        """
        nome_situacao = config.CAMPOS_STATUS_FINANCEIRO.get("situacao", "")
        seletor_pronto = (
            f"div[data-id='{nome_situacao}-FieldSectionItemContainer'] input, "
            f"div[data-id='{nome_situacao}'] input, "
            f"{config.SELETOR_GRID_EXTRATOS}"
        )
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, seletor_pronto))
            )
        except TimeoutException:
            pass  # segue mesmo assim — as esperas específicas de cada campo cobrem o resto

    # ------------------------------------------------------------------
    # Proteção contra instabilidade do Athenas na tela de mensalidade
    # ------------------------------------------------------------------
    # JS que classifica o estado da grade "Todos os Extratos":
    #   "linhas"    -> grade existe e tem linhas renderizadas
    #   "vazia"     -> grade existe e o PRÓPRIO GRID diz que não há registros
    #   "carregando"-> grade existe, mas sem linhas nem aviso de vazio
    #   "ausente"   -> grade nem apareceu na tela
    # O aviso de "vazio" é procurado SÓ dentro do wrapper desta grade — nunca
    # na página toda, senão uma outra sub-grade vazia da mesma tela poderia
    # ser confundida com "este aluno não tem extratos".
    _JS_ESTADO_GRADE = """
        const grid = document.querySelector(arguments[0]);
        if (!grid) return 'ausente';
        const wrapper = grid.closest('.ag-root-wrapper') || grid.parentElement || grid;
        if (grid.querySelector('div.ag-center-cols-container div[role="row"]')) return 'linhas';
        if (wrapper.querySelector('.ag-overlay-loading-wrapper, .ag-overlay-loading-center')) return 'carregando';
        if (wrapper.querySelector('.ag-overlay-no-rows-wrapper, .ag-overlay-no-rows-center')) return 'vazia';
        const texto = (wrapper.innerText || '').toLowerCase();
        const avisos = ['não encontramos nada', 'nenhum registro', 'não há dados', 'no data available', 'no records'];
        if (avisos.some(a => texto.includes(a))) return 'vazia';
        return 'carregando';
    """

    def _estado_grade_extratos(self) -> str:
        try:
            return self.driver.execute_script(self._JS_ESTADO_GRADE, config.SELETOR_GRID_EXTRATOS) or "ausente"
        except WebDriverException as erro:
            if self._e_erro_de_sessao_morta(erro):
                raise
            return "ausente"

    def _aguardar_tela_mensalidade(self, timeout: float):
        """
        Espera a tela de mensalidade ficar CONFIRMADAMENTE pronta e devolve:
          "linhas" -> grade com linhas estáveis
          "vazia"  -> a própria grade diz que não há registros
          None     -> nada disso até o timeout (ausente/carregando) — é
                      instabilidade, não "sem mensalidade".
        """
        fim = time.time() + timeout
        anterior = None
        estavel_desde = None
        while time.time() < fim:
            estado = self._estado_grade_extratos()
            if estado == "vazia":
                return "vazia"
            if estado == "linhas":
                atual = self._contagem_linhas_extrato()
                if atual > 0 and atual == anterior:
                    if estavel_desde is None:
                        estavel_desde = time.time()
                    elif time.time() - estavel_desde > 0.5:
                        return "linhas"
                else:
                    estavel_desde = None
                anterior = atual
            else:
                anterior, estavel_desde = None, None
            time.sleep(0.3)
        return None

    def _recarregar_financeiro(self, espera: float):
        """F5 na página do aluno, volta pra aba Financeiro e espera a grade.
        Devolve o mesmo que _aguardar_tela_mensalidade."""
        try:
            self.driver.refresh()
        except TimeoutException:
            pass  # página demorou pra "terminar" -- a espera abaixo decide se carregou
        except WebDriverException as erro:
            if self._e_erro_de_sessao_morta(erro):
                raise
        try:
            aba = WebDriverWait(self.driver, espera).until(
                EC.element_to_be_clickable((By.XPATH, config.XPATH_ABA_FINANCEIRO))
            )
            self._clicar(aba)
            time.sleep(0.6)
            self._definir_zoom(config.ZOOM_GRADE_FINANCEIRO)
            return self._aguardar_tela_mensalidade(espera)
        except (TimeoutException, StaleElementReferenceException, ErroConsultaRA):
            return None

    def _abrir_financeiro_com_recuperacao(self) -> str:
        """
        Abre a aba Financeiro e só devolve quando a tela de mensalidade
        carregou de verdade: "linhas" (grade com extratos) ou "vazia" (grade
        sem nenhum extrato, CONFIRMADA).

        - Não carregou: refresh (F5) e tenta de novo, até
          config.MAX_TENTATIVAS_REFRESH_FINANCEIRO vezes. Esgotado, levanta
          ErroCarregamentoAthenas — nunca vira "sem mensalidade".
        - Veio vazia: NÃO aceita de primeira (pode ser o Athenas devolvendo
          a grade vazia por instabilidade). Faz refresh e confere de novo,
          config.CONFIRMACOES_GRADE_VAZIA vez(es). Se aparecerem linhas, era
          instabilidade e segue normal; só devolve "vazia" se continuar vazia
          em todas as conferências.

        Seguro contra duplicidade: nada é gravado nem clicado no CRM (nenhuma
        checkbox, nenhum link) antes dessa etapa terminar; o refresh só
        recarrega a mesma tela de leitura do mesmo aluno.
        """
        espera = config.TIMEOUT_CARREGAMENTO_FINANCEIRO
        max_tentativas = config.MAX_TENTATIVAS_REFRESH_FINANCEIRO
        confirmacoes_vazia = config.CONFIRMACOES_GRADE_VAZIA

        try:
            self.ir_para_financeiro()
            estado = self._aguardar_tela_mensalidade(espera)
        except ErroConsultaRA:
            estado = None  # nem a aba apareceu -- mesma instabilidade, tenta recuperar

        tentativas_refresh = 0
        vezes_vazia = 0
        while True:
            self.log(f"  Tela de mensalidade carregada: {'SIM' if estado else 'NÃO'}")
            if estado == "linhas":
                if vezes_vazia:
                    self.log("  Grade de extratos: veio com linhas após o refresh (a grade vazia era instabilidade)")
                return "linhas"
            if estado == "vazia":
                vezes_vazia += 1
                self.log(f"  Grade de extratos: VAZIA (conferência {vezes_vazia}/{confirmacoes_vazia + 1})")
                if vezes_vazia > confirmacoes_vazia:
                    return "vazia"
                self.log("  Ação: Refresh para confirmar que a grade está vazia de verdade")
            else:
                if tentativas_refresh >= max_tentativas:
                    break
                tentativas_refresh += 1
                self.log(f"  Tentativa: {tentativas_refresh}/{max_tentativas}")
                self.log("  Ação: Refresh")
            self.log(f"  Aguardando carregamento: {espera}s")
            estado = self._recarregar_financeiro(espera)

        raise ErroCarregamentoAthenas(
            f"tela de mensalidade não carregou após {max_tentativas} tentativa(s) de refresh",
            tentativas=max_tentativas,
        )

    def _definir_zoom(self, porcentagem: int):
        try:
            self.driver.execute_script(f"document.body.style.zoom = '{porcentagem}%';")
            time.sleep(0.4)  # dá tempo pro reflow do layout terminar antes de interagir
        except WebDriverException:
            pass

    # ------------------------------------------------------------------
    # Leitura de campos do formulário (padrão FieldSectionItemContainer)
    # ------------------------------------------------------------------
    def _ler_campo(self, nome_logico: str, timeout: float = 4) -> str:
        """
        Lê o valor de um campo do formulário. IMPORTANTE: espera até
        `timeout` segundos pelo campo aparecer — antes isso era um
        find_element instantâneo sem nenhuma espera, o que fazia campos
        que ainda não tinham renderizado (ex: "Situação", logo depois de
        trocar de aba) vir sempre em branco, mesmo existindo na tela.

        Aceita mais de um padrão de seletor: já vimos nesse CRM seções
        onde o data-id vem com o sufixo "-FieldSectionItemContainer" e
        outras onde vem só o nome lógico puro (ex: "kcs_situacao"). Tenta
        os dois num seletor CSS só (o "," casa com qualquer um dos dois).
        """
        if not nome_logico:
            return ""
        seletor = (
            f"div[data-id='{nome_logico}-FieldSectionItemContainer'] input, "
            f"div[data-id='{nome_logico}'] input"
        )

        def _valor_preenchido(driver):
            """Condição pro WebDriverWait: só considera "pronto" quando o
            elemento existe E já tem um valor de verdade (não vazio). Ele
            pode renderizar no DOM vazio primeiro e o valor chegar um
            instante depois (componente controlado tipo React/Fluent UI) —
            esperar só a presença do elemento não é suficiente."""
            try:
                elemento = driver.find_element(By.CSS_SELECTOR, seletor)
            except NoSuchElementException:
                return False
            valor = (elemento.get_attribute("value") or elemento.get_attribute("title") or "").strip()
            return elemento if valor else False

        try:
            elemento = WebDriverWait(self.driver, timeout).until(_valor_preenchido)
            valor = elemento.get_attribute("value") or elemento.get_attribute("title") or ""
            return valor.strip()
        except TimeoutException:
            # não conseguiu um valor preenchido a tempo — tenta uma última
            # leitura (mesmo vazia) antes de desistir de vez, só pra não
            # perder um valor que porventura chegou bem na borda do timeout
            try:
                elemento = self.driver.find_element(By.CSS_SELECTOR, seletor)
                valor = (elemento.get_attribute("value") or elemento.get_attribute("title") or "").strip()
                if valor:
                    return valor
            except NoSuchElementException:
                pass
            self.log(f"  [aviso] campo '{nome_logico}' não encontrado (ou ficou vazio) na tela em {timeout}s.")
            return ""

    def extrair_dados_cadastro(self) -> dict:
        dados = {}
        for chave, nome_logico in config.CAMPOS_CADASTRO.items():
            dados[chave] = self._ler_campo(nome_logico)
        return dados

    def extrair_status_financeiro(self) -> dict:
        """Lê a seção 'Status Financeiro' da aba Financeiro — hoje só a Situação
        (Inadimplente/Adimplente); o campo 'Status Financeiro' em si não é mais usado."""
        dados = {}
        for chave, nome_logico in config.CAMPOS_STATUS_FINANCEIRO.items():
            dados[chave] = self._ler_campo(nome_logico)
        return dados

    # ------------------------------------------------------------------
    # Grade "Todos os Extratos"
    # ------------------------------------------------------------------
    def _linhas_extrato(self):
        """Só linhas de dentro da grade 'Todos os Extratos' (escopado por
        aria-label), pra nunca misturar com nenhuma outra grid da tela."""
        return self.driver.find_elements(By.CSS_SELECTOR, config.SELETOR_LINHAS_EXTRATOS)

    def _rolar_grade_extratos(self, para_extrema_direita: bool = False):
        """Rola o viewport horizontal da grade 'Todos os Extratos' pra extrema
        esquerda (padrão) ou direita. Grids virtualizados só mantêm no DOM as
        colunas dentro (ou perto) da área visível — colunas fora da tela
        somem do HTML até a gente rolar até elas."""
        try:
            viewport = self.driver.find_element(
                By.CSS_SELECTOR, f"{config.SELETOR_GRID_EXTRATOS} .ag-body-viewport"
            )
            alvo = "arguments[0].scrollWidth" if para_extrema_direita else "0"
            self.driver.execute_script(f"arguments[0].scrollLeft = {alvo};", viewport)
            time.sleep(0.15)
        except NoSuchElementException:
            pass

    def _rolar_ate_coluna(self, mes: str, ano: str, col_id: str, incremento_px: int = 350, tentativas_max: int = 10):
        """
        Rola a grade AOS POUCOS (em vez de pular direto pro extremo direito)
        até a coluna col_id aparecer no DOM pra linha do mês/ano informado.

        Por quê: a grade tem mais colunas depois de "Origem" (Tipo, Em
        Contestação, etc. — 21 colunas ao todo). Pular direto pro extremo
        direito pode empurrar justamente as colunas que a gente quer (Status
        da Fatura, Origem) pra fora de novo, do outro lado. Rolar aos poucos
        e checar a cada passo evita esse "efeito gangorra".

        Devolve a linha (referência sempre fresca) assim que achar a coluna,
        ou a última referência obtida se não conseguir depois de várias
        tentativas.
        """
        linha = self._localizar_linha_parcela(mes, ano)
        if linha is None:
            return None
        try:
            linha.find_element(By.CSS_SELECTOR, f"div[col-id='{col_id}']")
            return linha  # já está visível, nem precisa rolar
        except (NoSuchElementException, StaleElementReferenceException):
            pass

        try:
            viewport = self.driver.find_element(
                By.CSS_SELECTOR, f"{config.SELETOR_GRID_EXTRATOS} .ag-body-viewport"
            )
        except NoSuchElementException:
            return linha

        for _ in range(tentativas_max):
            try:
                self.driver.execute_script(
                    "arguments[0].scrollLeft = arguments[0].scrollLeft + arguments[1];",
                    viewport, incremento_px,
                )
            except WebDriverException:
                break
            time.sleep(0.15)

            linha = self._localizar_linha_parcela(mes, ano)
            if linha is None:
                continue
            try:
                linha.find_element(By.CSS_SELECTOR, f"div[col-id='{col_id}']")
                return linha  # achou
            except (NoSuchElementException, StaleElementReferenceException):
                continue

        return linha  # não achou depois de tudo — devolve o que tiver, mesmo assim

    def _valor_celula(self, linha, col_id: str) -> str:
        """Lê o texto de uma célula. IMPORTANTE: não tenta rolar+repetir aqui
        dentro — se a coluna não estiver renderizada (fora da área visível
        do grid virtualizado), quem chama precisa rolar E relocalizar a
        linha (referência nova), senão dá 'stale element reference'."""
        if not col_id:
            return ""
        try:
            return linha.find_element(By.CSS_SELECTOR, f"div[col-id='{col_id}']").text.strip()
        except (NoSuchElementException, StaleElementReferenceException):
            return ""

    def _contagem_linhas_extrato(self) -> int:
        try:
            return len(self._linhas_extrato())
        except StaleElementReferenceException:
            return -1

    def _aguardar_grade_extratos_carregada(self, timeout: float = None, estabilidade: float = 0.25):
        """
        Espera a grade 'Todos os Extratos' terminar de carregar as linhas —
        checagem LEVE (só a quantidade de linhas). A checkbox renderiza
        junto com o resto da linha (confirmado testando manualmente), não
        depois — então não precisa (e não deve) checar ela separadamente
        aqui; isso só fazia a espera queimar o timeout inteiro à toa
        sempre que a checagem da checkbox falhava por qualquer detalhe de
        seletor, mesmo com a grade 100% pronta.
        """
        timeout = timeout if timeout is not None else config.TIMEOUT_ESTABILIZACAO_GRID
        fim = time.time() + timeout
        anterior = None
        estavel_desde = None

        while time.time() < fim:
            atual = self._contagem_linhas_extrato()
            if atual > 0 and atual == anterior:
                if estavel_desde is None:
                    estavel_desde = time.time()
                elif time.time() - estavel_desde > estabilidade:
                    return
            else:
                estavel_desde = None
            anterior = atual
            time.sleep(0.2)

    def _localizar_linha_parcela(self, mes: str, ano: str):
        """
        Varre as linhas AGORA (referência sempre fresca) e devolve a que
        bate com o mês/ano informado, ou None.

        Se houver mais de uma linha pro MESMO mês/ano — comum depois de
        uma renegociação, o CRM mantém a parcela antiga e a nova ao mesmo
        tempo, com números de parcela diferentes — pega a de MAIOR número
        de parcela (é o critério pedido pra desempate).
        """
        melhor_linha = None
        melhor_numero_parcela = -1
        for linha in self._linhas_extrato():
            competencia = self._valor_celula(linha, config.COL_COMPETENCIA)
            ano_linha = self._valor_celula(linha, config.COL_ANO).replace(".", "").strip()
            if competencia.lower() != mes.lower() or ano_linha != str(ano):
                continue
            texto_parcela = self._valor_celula(linha, config.COL_PARCELA).strip()
            numero_parcela = int(texto_parcela) if texto_parcela.isdigit() else -1
            if numero_parcela > melhor_numero_parcela:
                melhor_numero_parcela = numero_parcela
                melhor_linha = linha
        return melhor_linha

    def _abrir_menu_cabecalho(self, cabecalho) -> bool:
        """
        Tenta abrir o menu de opções de um cabeçalho de coluna (o Callout
        com 'Do menor para o maior' / 'Do maior para o menor' etc.).
        Tenta clicar em candidatos diferentes dentro do cabeçalho — o
        botão da coluna como um todo, e especificamente o ícone de seta
        (▾) — até o menu realmente aparecer no DOM, conferindo depois de
        cada tentativa. Devolve True se o menu abriu.

        IMPORTANTE: todo ponto que usa a referência `cabecalho` (que foi
        obtida ANTES desta função ser chamada) está protegido contra
        StaleElementReferenceException — se a grade se re-renderizar entre
        um clique e outro (comum nesse CRM), a referência antiga "morre" e
        sem essa proteção o erro escapava até travar o RA inteiro.
        """
        candidatos = []
        try:
            candidatos.append(cabecalho.find_element(By.CSS_SELECTOR, "div[role='button']"))
        except (NoSuchElementException, StaleElementReferenceException):
            pass
        try:
            candidatos.append(cabecalho.find_element(By.CSS_SELECTOR, "i[data-icon-name='ChevronDownSmall']"))
        except (NoSuchElementException, StaleElementReferenceException):
            pass
        candidatos.append(cabecalho)  # último recurso: a própria célula do cabeçalho

        for candidato in candidatos:
            try:
                self._clicar(candidato)
            except (ErroConsultaRA, StaleElementReferenceException):
                continue
            time.sleep(0.4)
            try:
                if self.driver.find_elements(By.CSS_SELECTOR, "div[data-testid='columnContextMenu']"):
                    return True
            except WebDriverException:
                pass
        return False

    def _ordenar_grade_por_ano_desc(self, tentativas_max: int = 2):
        """
        Ordena a coluna 'Ano' do maior pro menor (ano mais recente sempre
        no topo). Combinado com _garantir_ano_carregado(), evita que
        faturas do ano atual fiquem escondidas pela virtualização vertical
        em alunos com muitas mensalidades.

        Clicar no cabeçalho não ordena direto — abre um menu (Callout)
        com opções. O botão certo, confirmado no HTML real do CRM, é:

            <button data-automation-id="sortZtoAId" ...>Do maior para o menor</button>

        Então abre o menu (_abrir_menu_cabecalho) e clica direto nesse
        `data-automation-id`, sem depender de achar o texto certo.

        Essa função inteira é só uma OTIMIZAÇÃO (garantir que o ano mais
        recente fica no topo) — nunca deve derrubar a consulta do RA. Por
        isso todo ponto que toca elementos já obtidos antes trata
        StaleElementReferenceException como "essa tentativa não deu
        certo, segue a vida", nunca deixando o erro escapar.
        """
        seletor_cabecalho = f"{config.SELETOR_GRID_EXTRATOS} div.ag-header-cell[col-id='{config.COL_ANO}']"
        seletor_opcao_desc = "button[data-automation-id='sortZtoAId']"

        for _ in range(tentativas_max):
            try:
                cabecalho = self.driver.find_element(By.CSS_SELECTOR, seletor_cabecalho)
                if cabecalho.get_attribute("aria-sort") == "descending":
                    return  # já está ordenado — nada a fazer
            except (NoSuchElementException, StaleElementReferenceException):
                return

            try:
                menu_abriu = self._abrir_menu_cabecalho(cabecalho)
            except StaleElementReferenceException:
                continue  # a referência morreu no meio do caminho — tenta de novo do zero
            if not menu_abriu:
                continue  # não conseguiu abrir o menu nessa tentativa — tenta de novo

            try:
                opcao_desc = self.driver.find_element(By.CSS_SELECTOR, seletor_opcao_desc)
            except NoSuchElementException:
                try:
                    self.driver.switch_to.active_element.send_keys(Keys.ESCAPE)
                except WebDriverException:
                    pass
                continue

            try:
                self._clicar(opcao_desc)
            except (ErroConsultaRA, StaleElementReferenceException):
                pass
            time.sleep(0.4)

    def _rolar_grade_extratos_vertical(self, incremento_px: int = 400):
        """Rola o viewport VERTICAL da grade 'Todos os Extratos' (linhas,
        diferente de _rolar_grade_extratos que é horizontal/colunas)."""
        try:
            viewport = self.driver.find_element(
                By.CSS_SELECTOR, f"{config.SELETOR_GRID_EXTRATOS} .ag-body-viewport"
            )
            self.driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollTop + arguments[1];", viewport, incremento_px
            )
        except NoSuchElementException:
            pass

    def _garantir_ano_carregado(self, ano_alvo: str, tentativas_max: int = 20):
        """
        Garante que todas as linhas do ano-alvo já estão carregadas na
        grade (não escondidas por virtualização vertical), rolando pra
        baixo se precisar. Como a grade está ordenada com o ano mais
        recente no topo (_ordenar_grade_por_ano_desc), a lógica é: se já
        enxergamos alguma linha de um ano ANTERIOR ao alvo entre as linhas
        atualmente renderizadas, é sinal de que tudo do ano-alvo já
        carregou (nada ficou escondido acima dela). Se não enxergamos
        ainda, rola mais um pouco — e para sozinho se a lista de linhas
        parar de crescer (sinal de que chegou ao fim dos dados de verdade,
        sem mais nada escondido).
        """
        try:
            ano_alvo_num = int(str(ano_alvo).strip())
        except ValueError:
            return

        contagem_anterior = -1
        for _ in range(tentativas_max):
            linhas = self._linhas_extrato()
            anos_vistos = set()
            for linha in linhas:
                texto_ano = self._valor_celula(linha, config.COL_ANO).replace(".", "").strip()
                if texto_ano.isdigit():
                    anos_vistos.add(int(texto_ano))
            if any(ano < ano_alvo_num for ano in anos_vistos):
                return  # já vemos um ano anterior -- o ano-alvo está completo
            if len(linhas) == contagem_anterior:
                return  # parou de crescer -- chegou ao fim dos dados
            contagem_anterior = len(linhas)
            self._rolar_grade_extratos_vertical()
            time.sleep(0.25)

    def localizar_parcela(self, mes: str, ano: str):
        """
        Espera a grade 'Todos os Extratos' carregar (checagem rápida) e
        procura a linha cujo mês/ano de competência bate com o solicitado.
        Retorna um dicionário com os dados da parcela, ou None se não
        encontrar (sem ficar esperando o timeout inteiro nesse caso — se a
        linha não existe, não existe, não adianta esperar mais).

        LEITURA ÚNICA: como a aba Financeiro já entra com o zoom reduzido
        (ver ir_para_financeiro/config.ZOOM_GRADE_FINANCEIRO), a grade
        inteira — as 21 colunas — já cabe na tela de uma vez, sem precisar
        rolar. Antes disso a gente lia em duas passadas com rolagem no
        meio, o que era a maior fonte de demora pra marcar a checkbox.
        Se AINDA ASSIM alguma coluna vier vazia (tela pequena demais pro
        zoom configurado dar conta, por exemplo), tenta de novo rolando
        até ela, só como reserva.

        Também ordena a grade por Ano decrescente e garante (rolando
        verticalmente se precisar) que nenhuma linha do ano pesquisado
        ficou escondida por virtualização — importante pra alunos com
        muitas mensalidades acumuladas.
        """
        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, config.SELETOR_GRID_EXTRATOS)))
        except TimeoutException:
            # A grade não apareceu: isso é falha de carregamento, NÃO ausência
            # de parcela. Antes devolvia None aqui, o que virava "sem
            # mensalidade" no resultado — exatamente o bug a evitar.
            raise ErroCarregamentoAthenas("grade 'Todos os Extratos' não apareceu na hora de localizar a parcela")

        self._aguardar_grade_extratos_carregada()

        # essas duas chamadas são só uma OTIMIZAÇÃO (garantir que o ano mais
        # recente fica visível, sem precisar rolar depois) — nunca deve
        # derrubar a consulta do RA. Se algo escapar mesmo com toda a
        # blindagem interna dessas funções, cai aqui e só segue sem essa
        # garantia extra, em vez de estourar um erro pro RA inteiro.
        try:
            self._ordenar_grade_por_ano_desc()
            self._aguardar_grade_extratos_carregada()  # a ordenação re-renderiza -- espera estabilizar de novo
            self._garantir_ano_carregado(ano)
        except (StaleElementReferenceException, WebDriverException) as erro:
            self.log(f"  [aviso] não consegui ordenar/garantir a grade por completo ({erro}) — seguindo mesmo assim.")

        linha = self._localizar_linha_parcela(mes, ano)
        if linha is None:
            return None

        # espera curta (não o timeout inteiro) pro valor sair de "Carregando..."
        fim = time.time() + min(1.5, self.timeout)
        while time.time() < fim:
            valor_atual = self._valor_celula(linha, config.COL_VALOR_ATUALIZADO)
            if valor_atual and "carregando" not in valor_atual.lower():
                break
            time.sleep(0.2)
            linha = self._localizar_linha_parcela(mes, ano) or linha

        dados = {
            "Competencia": self._valor_celula(linha, config.COL_COMPETENCIA),
            "Ano": self._valor_celula(linha, config.COL_ANO).replace(".", "").strip(),
            "Valor Atualizado": self._valor_celula(linha, config.COL_VALOR_ATUALIZADO),
            "Data Pagamento": self._valor_celula(linha, config.COL_DATA_PAGAMENTO),
            "Valor Pago": self._valor_celula(linha, config.COL_VALOR_PAGO),
            "Meio de Pagamento": self._valor_celula(linha, config.COL_MEIO_PAGAMENTO),
            "Status da Fatura": self._valor_celula(linha, config.COL_STATUS_FATURA),
            "Origem": self._valor_celula(linha, config.COL_ORIGEM),
        }

        # reserva: se a coluna mais distante (Origem) veio vazia, pode ser
        # que o zoom configurado não seja suficiente pra essa tela — tenta
        # de novo rolando especificamente até ela
        if not dados["Origem"] and config.COL_ORIGEM:
            linha_direita = self._rolar_ate_coluna(mes, ano, config.COL_ORIGEM)
            if linha_direita is not None:
                dados["Data Pagamento"] = self._valor_celula(linha_direita, config.COL_DATA_PAGAMENTO) or dados["Data Pagamento"]
                dados["Valor Pago"] = self._valor_celula(linha_direita, config.COL_VALOR_PAGO) or dados["Valor Pago"]
                dados["Meio de Pagamento"] = self._valor_celula(linha_direita, config.COL_MEIO_PAGAMENTO) or dados["Meio de Pagamento"]
                dados["Status da Fatura"] = self._valor_celula(linha_direita, config.COL_STATUS_FATURA) or dados["Status da Fatura"]
                dados["Origem"] = self._valor_celula(linha_direita, config.COL_ORIGEM)
                self._rolar_grade_extratos(para_extrema_direita=False)  # devolve a checkbox pra visão

        return dados

    def capturar_parcelas_a_partir_de(
        self, mes_minimo: str, ano_minimo,
        mes_ja_gerado: str = None, ano_ja_gerado=None, link_ja_gerado: str = None,
    ) -> list:
        """
        Varre TODAS as linhas já carregadas da grade 'Todos os Extratos' e
        devolve uma lista de dicionários — um por parcela — com as colunas
        confirmadas, para toda competência >= mes_minimo/ano_minimo (ex:
        Junho/2026 em diante). Devolve ordenado do mês mais ANTIGO pro mais
        NOVO (Junho antes de Julho, etc).

        Pra CADA mês encontrado que ainda não esteja Pago/Negociado,
        também TENTA GERAR O LINK DE PAGAMENTO daquele mês específico
        (marca a checkbox da linha, clica em "Meio de Pagamento", lê o
        resultado) — vale pra todo mundo, não só quem está Inadimplente, e
        pode gerar mais de um link por aluno se houver mais de um mês em
        aberto. Isso é diferente do fluxo principal (que só olha mês
        seguinte/mês atual): aqui sempre confere desde o mês/ano mínimo
        configurado em diante, mesmo que já tenha passado.

        Se `mes_ja_gerado`/`ano_ja_gerado` forem informados (o mês que o
        fluxo PRINCIPAL já processou pra esse mesmo RA), REAPROVEITA o
        `link_ja_gerado` pra esse mês em vez de clicar tudo de novo — evita
        gerar o mesmo link duas vezes pro mesmo aluno/mês.

        Autocontida: faz sua própria preparação da grade (espera carregar,
        ordena por Ano decrescente, garante que nada ficou escondido por
        virtualização vertical) — não depende de localizar_parcela ter
        rodado antes, embora normalmente já tenha rodado no fluxo real.
        """
        try:
            ano_min = int(str(ano_minimo).strip())
        except (TypeError, ValueError):
            ano_min = 0
        try:
            idx_mes_min = config.MESES.index(mes_minimo)
        except ValueError:
            idx_mes_min = 0

        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, config.SELETOR_GRID_EXTRATOS)))
        except TimeoutException:
            # lista vazia aqui viraria "Sem mensalidade" em todos os meses do
            # relatório -- sinaliza como falha de carregamento
            raise ErroCarregamentoAthenas("grade 'Todos os Extratos' não apareceu para o relatório de meses")

        self._aguardar_grade_extratos_carregada()
        try:
            self._ordenar_grade_por_ano_desc()
            self._aguardar_grade_extratos_carregada()
            self._garantir_ano_carregado(str(ano_min))
        except (StaleElementReferenceException, WebDriverException) as erro:
            self.log(f"  [aviso] relatório de meses: não consegui ordenar/garantir a grade por completo ({erro}).")

        # Deduplica por (Ano, Competência): uma renegociação cria DUAS
        # linhas pro mesmo mês (a parcela antiga e a nova), com números de
        # parcela diferentes — mantém sempre a de MAIOR número de parcela,
        # descarta a outra.
        melhores_por_mes = {}
        for linha in self._linhas_extrato():
            competencia = self._valor_celula(linha, config.COL_COMPETENCIA)
            ano_texto = self._valor_celula(linha, config.COL_ANO).replace(".", "").strip()
            if not ano_texto.isdigit() or competencia not in config.MESES:
                continue
            ano_linha = int(ano_texto)
            idx_mes_linha = config.MESES.index(competencia)
            if (ano_linha, idx_mes_linha) < (ano_min, idx_mes_min):
                continue  # mais antigo que o mínimo configurado -- ignora

            texto_parcela = self._valor_celula(linha, config.COL_PARCELA).strip()
            numero_parcela = int(texto_parcela) if texto_parcela.isdigit() else -1

            chave = (ano_linha, competencia)
            existente = melhores_por_mes.get(chave)
            if existente is not None and existente["_numero_parcela"] >= numero_parcela:
                continue  # já temos uma parcela igual ou maior pra esse mês -- ignora essa linha

            melhores_por_mes[chave] = {
                "_numero_parcela": numero_parcela,
                "Parcela": texto_parcela,
                "Competencia": competencia,
                "Ano": str(ano_linha),
                "Numero de Documento": self._valor_celula(linha, config.COL_NUMERO_DOCUMENTO),
                "Data Emissao": self._valor_celula(linha, config.COL_DATA_EMISSAO),
                "Liberacao Meio Pgto": self._valor_celula(linha, config.COL_LIBERACAO_MEIO_PGTO),
                "Valor Atualizado": self._valor_celula(linha, config.COL_VALOR_ATUALIZADO),
                "Valor Desc Pontualidade": self._valor_celula(linha, config.COL_VALOR_DESC_PONTUALIDADE),
                "Data Vencimento": self._valor_celula(linha, config.COL_DATA_VENCIMENTO),
                "Data Pagamento": self._valor_celula(linha, config.COL_DATA_PAGAMENTO),
                "Valor Pago": self._valor_celula(linha, config.COL_VALOR_PAGO),
                "Meio de Pagamento": self._valor_celula(linha, config.COL_MEIO_PAGAMENTO),
                "Status da Fatura": self._valor_celula(linha, config.COL_STATUS_FATURA),
                "Origem": self._valor_celula(linha, config.COL_ORIGEM),
                "Tipo": self._valor_celula(linha, config.COL_TIPO),
                "Em Contestacao": self._valor_celula(linha, config.COL_EM_CONTESTACAO),
                "Link Pagamento": "",  # por enquanto sempre vazio -- preenchido no loop abaixo
            }

        parcelas = list(melhores_por_mes.values())
        for parcela in parcelas:
            del parcela["_numero_parcela"]  # campo só de uso interno pro desempate, não vai pro resultado

        parcelas.sort(key=lambda p: (int(p["Ano"]), config.MESES.index(p["Competencia"])))

        # Pra CADA mês encontrado que ainda não esteja Pago/Negociado, tenta
        # gerar o link de pagamento daquele mês específico — diferente do
        # fluxo principal (que só olha mês seguinte/atual), aqui é
        # "sempre confere desde Junho/2026 em diante", vale pra todo mundo.
        for parcela in parcelas:
            status = (parcela.get("Status da Fatura") or "").strip().lower()
            if status in config.STATUS_FATURA_SEM_LINK:
                continue  # já pago/negociado -- não tenta gerar link
            mes_parcela, ano_parcela = parcela["Competencia"], parcela["Ano"]

            if (mes_ja_gerado and mes_parcela == mes_ja_gerado
                    and ano_ja_gerado is not None and str(ano_parcela) == str(ano_ja_gerado)):
                # o fluxo principal já processou esse mesmo mês pra esse RA
                # (mês seguinte/atual) -- reaproveita o link em vez de
                # marcar a checkbox e clicar tudo de novo à toa
                parcela["Link Pagamento"] = link_ja_gerado or ""
                continue

            max_tentativas_mes = 2  # sem resposta do CRM: tenta mais uma vez esse mês
            for tentativa_mes in range(1, max_tentativas_mes + 1):
                try:
                    self.marcar_checkbox_linha(mes_parcela, ano_parcela)
                    parcela["Link Pagamento"] = self.gerar_link_pagamento()
                    break
                except ErroDocumentoIndisponivel as erro:
                    parcela["Link Pagamento"] = ""  # CRM recusou -- resultado válido, não é erro
                    self.log(f"  [{mes_parcela}/{ano_parcela}] CRM: {erro}")
                    break
                except ErroRespostaAthenas as erro:
                    parcela["Link Pagamento"] = ""
                    if tentativa_mes < max_tentativas_mes:
                        self.log(f"  [{mes_parcela}/{ano_parcela}] CRM sem resposta — tentando de novo "
                                 f"({tentativa_mes + 1}/{max_tentativas_mes})")
                    else:
                        self.log(f"  [aviso] não consegui gerar link de {mes_parcela}/{ano_parcela}: {erro}")
                except (ErroConsultaRA, StaleElementReferenceException, TimeoutException, WebDriverException) as erro:
                    self.log(f"  [aviso] não consegui gerar link de {mes_parcela}/{ano_parcela}: {erro}")
                    parcela["Link Pagamento"] = ""
                    break
                finally:
                    # desmarca TUDO antes do próximo mês/tentativa (por estado,
                    # não por "clicar de novo") -- mais de uma linha marcada
                    # desabilita o botão 'Meio de Pagamento' no CRM
                    try:
                        self._limpar_selecao_extratos()
                    except Exception:  # pylint: disable=broad-except
                        pass

        return parcelas

    _JS_LINHAS_SELECIONADAS = """
        const rows = document.querySelectorAll(arguments[0]);
        return Array.from(rows).filter(r =>
            r.getAttribute('aria-selected') === 'true' || r.classList.contains('ag-row-selected')
        );
    """

    def _linhas_selecionadas(self):
        try:
            return self.driver.execute_script(self._JS_LINHAS_SELECIONADAS, config.SELETOR_LINHAS_EXTRATOS) or []
        except WebDriverException as erro:
            if self._e_erro_de_sessao_morta(erro):
                raise
            return []

    def _linha_esta_selecionada(self, linha) -> bool:
        try:
            if linha.get_attribute("aria-selected") == "true":
                return True
            return "ag-row-selected" in (linha.get_attribute("class") or "")
        except StaleElementReferenceException:
            return False

    def _limpar_selecao_extratos(self, tentativas: int = 3) -> bool:
        """
        Desmarca TODAS as linhas selecionadas da grade 'Todos os Extratos'.
        Com mais de uma linha marcada, o CRM desabilita o botão 'Meio de
        Pagamento' — então toda geração de link começa (e termina) com a
        grade sem nenhuma seleção. Confere o estado real a cada passada, em
        vez de "clicar de novo e torcer" (o que invertia a seleção quando um
        clique falhava). Devolve True se a grade ficou sem seleção.
        """
        for _ in range(tentativas):
            selecionadas = self._linhas_selecionadas()
            if not selecionadas:
                return True
            for linha in selecionadas:
                try:
                    checkbox = linha.find_element(By.CSS_SELECTOR, "div[col-id='__row_status'] input[type='checkbox']")
                    self._clicar(checkbox)
                    time.sleep(0.2)
                except (NoSuchElementException, StaleElementReferenceException, ErroConsultaRA):
                    continue
        restantes = len(self._linhas_selecionadas())
        if restantes:
            self.log(f"  [aviso] não consegui desmarcar {restantes} linha(s) da grade de extratos.")
        return restantes == 0

    def marcar_checkbox_linha(self, mes: str, ano: str, tentativas: int = 3):
        """
        Relocaliza a linha do mês/ano NA HORA (referência sempre fresca, nunca
        reaproveitada de uma busca anterior) e marca a checkbox dela.

        Com o zoom reduzido na aba Financeiro (config.ZOOM_GRADE_FINANCEIRO),
        a coluna da checkbox já fica visível sem precisar rolar — então NÃO
        rolamos mais em toda tentativa (isso era a maior fonte da demora de
        10-15s pra marcar a checkbox). Só rola como reserva se a checkbox
        não for encontrada de primeira (ex: zoom insuficiente pra essa tela).

        Tenta algumas vezes, relocalizando tudo do zero a cada tentativa: o
        grid pode "reciclar" a linha (destruir e recriar o nó do DOM) entre
        localizar e clicar, o que dá 'stale element reference' — a única
        forma confiável de lidar com isso é pegar uma referência nova e
        tentar de novo, nunca insistir na referência que já falhou.
        """
        ultimo_erro = None
        if not self._limpar_selecao_extratos():
            raise ErroConsultaRA(
                f"Havia linhas marcadas na grade que não consegui desmarcar antes de marcar {mes}/{ano}."
            )
        for tentativa in range(1, tentativas + 1):
            linha = self._localizar_linha_parcela(mes, ano)
            if linha is None:
                raise ErroConsultaRA(
                    f"Não encontrei mais a linha de {mes}/{ano} na grade 'Todos os Extratos' "
                    "na hora de marcar a checkbox (ela pode ter recarregado)."
                )
            try:
                celula_checkbox = linha.find_element(By.CSS_SELECTOR, "div[col-id='__row_status']")
                checkbox = celula_checkbox.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
            except NoSuchElementException:
                if tentativa == 1:
                    # reserva: talvez o zoom não tenha sido suficiente —
                    # rola pra esquerda explicitamente e tenta mais uma vez
                    self._rolar_grade_extratos(para_extrema_direita=False)
                    continue
                raise ErroConsultaRA(
                    f"A linha de {mes}/{ano} foi encontrada, mas não tem checkbox de seleção "
                    "(pode ser que essa parcela não permita gerar link, ou o layout da grade mudou)."
                )
            except StaleElementReferenceException as erro:
                ultimo_erro = erro
                time.sleep(0.3)
                continue

            try:
                if not self._linha_esta_selecionada(linha):
                    self._rolar_ate(celula_checkbox)
                    self._clicar(checkbox)
                    time.sleep(0.3)
                # confere o estado real: exatamente esta linha selecionada
                linha = self._localizar_linha_parcela(mes, ano)
                if linha is not None and self._linha_esta_selecionada(linha) and len(self._linhas_selecionadas()) == 1:
                    return  # sucesso
                ultimo_erro = "a seleção não ficou só na linha do mês"
                self._limpar_selecao_extratos()
                continue
            except (ErroConsultaRA, StaleElementReferenceException) as erro:
                ultimo_erro = erro
                time.sleep(0.3)
                continue

        raise ErroConsultaRA(
            f"Não consegui marcar a checkbox de {mes}/{ano} depois de {tentativas} tentativas "
            f"(a linha ficou 'reciclando' no grid): {ultimo_erro}"
        )

    # ------------------------------------------------------------------
    # Botão "Meio de Pagamento" + modal (link de sucesso OU recusa do CRM)
    # ------------------------------------------------------------------
    def _aguardar_texto_modal(self, timeout: float = None):
        """
        Espera o texto da mensagem do modal aparecer. O MESMO seletor
        (span[data-id='dialogMessageText']) é usado tanto no modal de
        sucesso ("Link do Meio de Pagamento", com um link) quanto no modal
        de recusa do próprio CRM ("Documento não disponível, verifique o
        status da fatura.") — só o modal de sucesso tem um <h1> de título,
        então não podemos depender dele pra saber que o modal abriu.
        Devolve o texto, ou None se nada apareceu a tempo.
        """
        timeout = timeout or self.timeout
        try:
            elemento = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, config.SELETOR_MODAL_TEXTO_LINK))
            )
            return elemento.text.strip()
        except TimeoutException:
            return None

    def _fechar_modal_se_houver(self):
        try:
            fechar = self.driver.find_element(By.CSS_SELECTOR, config.SELETOR_MODAL_BOTAO_FECHAR)
            self._clicar(fechar)
            time.sleep(0.2)
        except NoSuchElementException:
            pass

    def gerar_link_pagamento(self) -> str:
        """
        Clica no botão 'Meio de Pagamento' e devolve o link gerado.

        Se o CRM recusar (fatura já paga, documento indisponível etc.), ele
        mostra um modal com uma mensagem de texto em vez de um link — nesse
        caso, levanta ErroDocumentoIndisponivel (é tratado à parte pelo
        chamador, não como uma falha da automação).
        """
        try:
            botao = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, config.XPATH_BOTAO_MEIO_PAGAMENTO))
            )
        except TimeoutException:
            raise ErroConsultaRA(
                "Botão 'Meio de Pagamento' não ficou disponível (marque a checkbox da "
                "parcela antes de chamar esta função)."
            )
        self._clicar(botao)
        texto_modal = self._aguardar_texto_modal()

        if texto_modal is None:
            # o clique pode não ter "pego" da primeira vez (grid virtualizado) — tenta mais uma vez
            self._fechar_modal_se_houver()
            self._clicar(botao)
            texto_modal = self._aguardar_texto_modal()

        self._fechar_modal_se_houver()

        if texto_modal is None:
            raise ErroRespostaAthenas("Nenhuma resposta do sistema apareceu a tempo depois de clicar em 'Meio de Pagamento'.")

        if texto_modal.lower().startswith("http"):
            return texto_modal

        # o CRM respondeu, mas recusou gerar o documento — não é uma falha
        # da automação, é uma resposta válida do sistema (ex: fatura paga)
        raise ErroDocumentoIndisponivel(texto_modal)

    def _mes_ano_atual(self):
        """Nome do mês (conforme config.MESES) e ano (string) da data de hoje."""
        agora = datetime.now()
        return config.MESES[agora.month - 1], str(agora.year)

    def _mes_ano_seguinte(self):
        """Nome do mês e ano do mês seguinte ao atual (considera virada de ano)."""
        agora = datetime.now()
        if agora.month == 12:
            return config.MESES[0], str(agora.year + 1)
        return config.MESES[agora.month], str(agora.year)

    # ------------------------------------------------------------------
    # Fluxo completo para um RA
    # ------------------------------------------------------------------
    def _montar_nome_completo(self, nome: str, sobrenome: str) -> str:
        """Junta nome + sobrenome num nome completo só, sem espaços duplicados
        nem sobrando se um dos dois vier vazio."""
        partes = [p.strip() for p in (nome, sobrenome) if p and p.strip()]
        return " ".join(partes)

    def _limpar_celular(self, numero: str) -> str:
        """Tira tudo que não for dígito (espaço, parênteses, hífen) e coloca
        o DDI 55 na frente. Ex: '(15) 99751-2820' -> '5515997512820'."""
        apenas_digitos = re.sub(r"\D", "", numero or "")
        if not apenas_digitos:
            return ""
        return "55" + apenas_digitos

    def _observar_campos_criticos_vazios(self, registro: dict):
        """
        'Trava' de qualidade: confere se os campos mais importantes do
        Cadastro (CPF, Nome, Celular, E-mail) vieram vazios mesmo sem
        nenhum erro ter sido lançado — isso pode acontecer se a tela
        carregou parcialmente sem dar erro explícito. Em vez de deixar
        passar batido como "OK" normal, marca um aviso bem visível no
        Status da Consulta, pra esse RA não passar despercebido na
        planilha final e alguém conferir manualmente.
        """
        campos_criticos = {
            "CPF": registro.get("CPF"),
            "Nome": registro.get("Nome"),
            "Celular": registro.get("Celular"),
            "E-mail": registro.get("E-mail"),
        }
        vazios = [nome for nome, valor in campos_criticos.items() if not valor]
        if not vazios:
            return
        aviso = f"AVISO: campo(s) vazio(s) - {', '.join(vazios)} (conferir manualmente)"
        status_atual = registro.get("Status da Consulta", "OK")
        if aviso not in status_atual:
            registro["Status da Consulta"] = f"{status_atual} | {aviso}"

    def consultar_ra(self, ra: str) -> dict:
        """
        Executa o fluxo completo para um único RA e devolve um dicionário já
        no formato das colunas de saída (config.COLUNAS_SAIDA). Não depende
        de o usuário escolher mês/ano: a automação decide sozinha, nesta
        ordem de prioridade:

        1. Fatura do mês SEGUINTE ao atual já está disponível? Usa ela.
        2. Senão, usa a fatura do mês VIGENTE.
        3. Se nenhuma das duas existir na grade, marca "Mensalidade
           Encontrada" = Não.

        Os dados de pagamento (Data Pagamento, Valor Pago, Meio de
        Pagamento, Status da Fatura, Origem) que já vierem prontos na grade
        são sempre gravados no resultado, estejam pagos ou não. Depois, a
        automação SEMPRE tenta gerar o link de pagamento — é o próprio CRM
        quem decide se libera (fatura em aberto) ou recusa (ex: já paga,
        mostrando "Documento não disponível"); nesse segundo caso a
        automação apenas registra isso, sem tratar como erro.
        """
        registro = {coluna: "" for coluna in config.COLUNAS_SAIDA}
        registro["RA"] = ra
        # "Não" só é gravado depois que a consulta foi feita de verdade e
        # confirmou que não há mensalidade. Em qualquer falha antes disso,
        # fica "Não consultada" -- nunca parece "sem mensalidade".
        registro["Mensalidade Encontrada"] = "Não consultada"
        registro["Status da Consulta"] = "OK"
        registro["_relatorio_consultado"] = False

        self._ra_atual = ra
        self.log("Início da consulta")
        try:
            self.abrir_lista_alunos()
            self.buscar_ra(ra)
            registro["Curso"] = self.abrir_registro_do_resultado(ra)
            self.log("  Cadastro localizado: SIM")

            # --- aba Cadastro ---
            self.ir_para_cadastro()
            dados_cadastro = self.extrair_dados_cadastro()
            registro["CPF"] = dados_cadastro.get("cpf", "")
            registro["Nome"] = self._montar_nome_completo(
                dados_cadastro.get("nome", ""), dados_cadastro.get("sobrenome", "")
            )
            registro["Celular"] = self._limpar_celular(dados_cadastro.get("celular", ""))
            registro["E-mail"] = dados_cadastro.get("email", "")

            # --- aba Financeiro (com proteção contra instabilidade do Athenas) ---
            estado_grade = self._abrir_financeiro_com_recuperacao()

            status_fin = self.extrair_status_financeiro()
            registro["Situacao"] = status_fin.get("situacao", "")

            if estado_grade == "vazia":
                # confirmado com refresh: o CRM não tem NENHUM extrato pra
                # esse aluno. Diferente de "sem mensalidade do mês" -- fica
                # destacado pra conferência manual, com print como prova.
                registro["Mensalidade Encontrada"] = "Não (nenhum extrato no CRM)"
                registro["Resultado da Consulta"] = RESULTADO_SEM_EXTRATOS
                registro["Status da Consulta"] = (
                    "OK (nenhum extrato no CRM, confirmado após refresh - conferir manualmente)"
                )
                registro["_parcelas_relatorio"] = []
                registro["_relatorio_consultado"] = True
                self.log("  Consulta realizada: SIM")
                self.log("  Mensalidade encontrada: NÃO (grade de extratos vazia no CRM)")
                self._salvar_screenshot_erro(ra, "sem_extratos_no_crm")
                self._observar_campos_criticos_vazios(registro)
                self.log(f"  Status final: {RESULTADO_SEM_EXTRATOS}")
                return registro

            mes_atual, ano_atual = self._mes_ano_atual()
            mes_seguinte, ano_seguinte = self._mes_ano_seguinte()

            # decide qual fatura usar: prioriza a do mês seguinte se já existir
            dados_parcela = self.localizar_parcela(mes_seguinte, ano_seguinte)
            mes_alvo, ano_alvo = mes_seguinte, ano_seguinte
            if dados_parcela is None:
                dados_parcela = self.localizar_parcela(mes_atual, ano_atual)
                mes_alvo, ano_alvo = mes_atual, ano_atual

            # guarda mês/ano/link do fluxo principal, se algum, pra passar
            # pro relatório de meses reaproveitar (evita gerar o mesmo link
            # duas vezes pro mesmo RA)
            mes_reutilizavel = ano_reutilizavel = link_reutilizavel = None

            self.log("  Consulta realizada: SIM")

            if dados_parcela is None:
                # só chega aqui com a tela CONFIRMADAMENTE carregada
                # (_abrir_financeiro_com_recuperacao) -- é ausência real
                registro["Mensalidade Encontrada"] = "Não"
                registro["Resultado da Consulta"] = RESULTADO_SEM_MENSALIDADE
                registro["Status da Consulta"] = (
                    f"OK (sem mensalidade de {mes_atual}/{ano_atual} disponível)"
                )
                self.log("  Mensalidade encontrada: NÃO")
            else:
                registro["Mensalidade Encontrada"] = "Sim"
                registro["Resultado da Consulta"] = RESULTADO_SUCESSO_COM_MENSALIDADE
                self.log("  Mensalidade encontrada: SIM")
                registro.update(dados_parcela)  # sempre traz o que veio da grade, pago ou não

                status_fatura = (dados_parcela.get("Status da Fatura") or "").strip().lower()
                if status_fatura in config.STATUS_FATURA_SEM_LINK:
                    # já sabemos (coluna confirmada) que não precisa de link —
                    # "Pago" ou "Negociado": só traz os dados da grade e segue
                    # pro próximo RA, sem tentar gerar link nem clicar em nada
                    registro["Link de Pagamento"] = ""
                else:
                    try:
                        self.marcar_checkbox_linha(mes_alvo, ano_alvo)
                        registro["Link de Pagamento"] = self.gerar_link_pagamento()
                        registro["Data/Hora do Link"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                    except ErroDocumentoIndisponivel as erro:
                        # o CRM recusou por algum outro motivo (ex: "Cancelado") —
                        # resultado válido, não é erro da automação. "Status da
                        # Fatura" continua fiel ao que veio da grade (mesmo que
                        # em branco) — o motivo da recusa fica registrado aqui,
                        # em "Status da Consulta", sem inventar valor na coluna.
                        registro["Link de Pagamento"] = ""
                        registro["Status da Consulta"] = f"OK (CRM: {erro})"
                    finally:
                        # não deixa a linha marcada pro relatório de meses
                        # (senão ficam 2 linhas marcadas e o botão trava)
                        self._limpar_selecao_extratos()

                mes_reutilizavel, ano_reutilizavel = mes_alvo, ano_alvo
                link_reutilizavel = registro["Link de Pagamento"]
                self.log(f"  Link localizado: {'SIM' if registro['Link de Pagamento'] else 'NÃO'}")

            # Relatório separado (arquivo novo, não mexe na lógica principal
            # acima): copia as parcelas a partir do mês/ano mínimo
            # configurado, reaproveitando o link que o fluxo principal já
            # gerou pro mês correspondente (se algum), em vez de gerar de
            # novo. Envolvido em try/except pra nunca derrubar o RA por
            # causa dele — é um "extra".
            try:
                registro["_parcelas_relatorio"] = self.capturar_parcelas_a_partir_de(
                    config.MES_MINIMO_RELATORIO, config.ANO_MINIMO_RELATORIO,
                    mes_ja_gerado=mes_reutilizavel, ano_ja_gerado=ano_reutilizavel,
                    link_ja_gerado=link_reutilizavel,
                )
                registro["_relatorio_consultado"] = True
            except Exception as erro:  # pylint: disable=broad-except
                self.log(f"  [aviso] não consegui montar o relatório de meses pra esse RA: {erro}")
                registro["_parcelas_relatorio"] = []

            self._observar_campos_criticos_vazios(registro)
            self.log(f"  Status final: {registro['Resultado da Consulta']}")

        except ErroCarregamentoAthenas as erro:
            registro["Resultado da Consulta"] = RESULTADO_ERRO_CARREGAMENTO
            registro["Status da Consulta"] = f"Erro: {RESULTADO_ERRO_CARREGAMENTO} - Instabilidade no Athenas ({erro})"
            self._forcar_reload_lista = True
            if erro.tentativas:
                self.log(f"  Tentativas realizadas: {erro.tentativas}")
            self.log(f"  Status final: {RESULTADO_ERRO_CARREGAMENTO}")
            self.log("  Motivo: Instabilidade no sistema de origem")
            self._salvar_screenshot_erro(ra, "erro_carregamento_athenas")
        except ErroRespostaAthenas as erro:
            registro["Resultado da Consulta"] = RESULTADO_TIMEOUT_ATHENAS
            registro["Status da Consulta"] = f"Erro: {RESULTADO_TIMEOUT_ATHENAS} - {erro}"
            self._forcar_reload_lista = True
            self.log(f"  Status final: {RESULTADO_TIMEOUT_ATHENAS}")
            self.log("  Motivo: o CRM não respondeu (instabilidade no sistema de origem)")
            self._salvar_screenshot_erro(ra, "sem_resposta_athenas")
        except ErroConsultaRA as erro:
            registro["Resultado da Consulta"] = RESULTADO_ERRO_CONSULTA
            registro["Status da Consulta"] = f"Erro: {erro}"
            self._forcar_reload_lista = True
            if self._e_erro_de_sessao_morta(erro):
                self.sessao_morta = True
                self.log(f"  [FATAL] a sessão do navegador parece ter morrido ({erro}).")
            else:
                self._salvar_screenshot_erro(ra, "erro_consulta")
        except (TimeoutException, StaleElementReferenceException) as erro:
            registro["Resultado da Consulta"] = RESULTADO_TIMEOUT_ATHENAS
            registro["Status da Consulta"] = f"Erro: tempo esgotado ou tela mudou ({erro})"
            self._forcar_reload_lista = True
            if self._e_erro_de_sessao_morta(erro):
                self.sessao_morta = True
                self.log(f"  [FATAL] a sessão do navegador parece ter morrido ({erro}).")
            else:
                self._salvar_screenshot_erro(ra, "timeout_ou_tela_mudou")
        except Exception as erro:  # pylint: disable=broad-except
            registro["Resultado da Consulta"] = RESULTADO_ERRO_CONSULTA
            registro["Status da Consulta"] = f"Erro inesperado: {erro}"
            self._forcar_reload_lista = True
            if self._e_erro_de_sessao_morta(erro):
                self.sessao_morta = True
                self.log(f"  [FATAL] a sessão do navegador parece ter morrido ({erro}).")
            else:
                self._salvar_screenshot_erro(ra, "erro_inesperado")

        return registro

    def _salvar_screenshot_erro(self, ra: str, contexto: str) -> str:
        """
        Salva um print da tela no momento do erro, em
        Documentos/CapturaLinkPagamento/logs/screenshots/. Nome do arquivo
        já identifica o RA, o tipo de erro e a hora, pra facilitar achar
        depois. Nunca deixa um problema aqui derrubar o resto da automação
        — se não conseguir printar, só ignora.
        """
        try:
            os.makedirs(config.PASTA_SCREENSHOTS, exist_ok=True)
            carimbo = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            nome_arquivo = f"{ra}_{contexto}_{carimbo}.png"
            caminho = os.path.join(config.PASTA_SCREENSHOTS, nome_arquivo)
            self.driver.save_screenshot(caminho)
            self.log(f"  [screenshot] erro salvo em: {caminho}")
            return caminho
        except Exception:  # pylint: disable=broad-except
            return ""