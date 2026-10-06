# -*- coding: utf-8 -*-
"""
limpeza.py
==========
Lógica do botão "Zerar painel (começar outro polo)": apaga o histórico e os
números do painel, a recuperação pendente, TODO o conteúdo das pastas de saída
e de prints de erro (as pastas em si ficam) e as bases de reprocessamento.

NUNCA apaga: perfis do Chrome (%LOCALAPPDATA%\\CapturaLinkPagamento\\perfis),
apelidos/e-mails dos perfis, credenciais do Windows, nem nada fora da pasta de
dados do programa (Documentos\\CapturaLinkPagamento).
"""
import os
import shutil

import config
import estilo
import history
import recuperacao


def _pastas_alvo() -> list:
    """Pastas cujo CONTEÚDO é apagado (as pastas em si são mantidas)."""
    return [
        config.PASTA_SAIDA,
        config.PASTA_SCREENSHOTS,
        os.path.join(config.PASTA_LOGS, "reprocessamentos"),
    ]


def _dentro_de(base: str, alvo: str) -> bool:
    base, alvo = os.path.realpath(base), os.path.realpath(alvo)
    try:
        return os.path.commonpath([base, alvo]) == base
    except ValueError:  # discos diferentes no Windows
        return False


def _eh_pasta_segura(pasta: str) -> bool:
    """Trava de segurança: só pode apagar DENTRO da pasta de dados do
    programa (e nunca a pasta de dados em si) — e jamais dentro da pasta
    local dos perfis do Chrome."""
    if not _dentro_de(config.PASTA_DOCUMENTOS, pasta):
        return False
    if os.path.realpath(pasta) == os.path.realpath(config.PASTA_DOCUMENTOS):
        return False
    if _dentro_de(config.PASTA_PERFIS, pasta) or _dentro_de(pasta, config.PASTA_PERFIS):
        return False
    if _dentro_de(config.PASTA_APP_LOCAL, pasta):
        return False
    return True


def _itens(pasta: str) -> list:
    if not os.path.isdir(pasta) or not _eh_pasta_segura(pasta):
        return []
    return [os.path.join(pasta, nome) for nome in os.listdir(pasta)]


def resumo() -> dict:
    """O que seria apagado agora (pra mostrar na confirmação)."""
    return {
        "execucoes_historico": len(history.carregar_historico()),
        "pastas_saida": sum(1 for i in _itens(config.PASTA_SAIDA) if os.path.isdir(i)),
        "itens_total": sum(len(_itens(p)) for p in _pastas_alvo()),
    }


def zerar_tudo(app=None, falhas_out: list = None) -> int:
    """
    Zera estatísticas e histórico, descarta a recuperação pendente e apaga
    todo o conteúdo das pastas de saída e de prints. Devolve QUANTOS itens
    não puderam ser apagados (ex: arquivo aberto no Excel); os caminhos
    deles vão para `falhas_out`, se informado. O resto segue sendo apagado.
    `app` (opcional) é a janela principal — usada pra zerar os contadores em memória.
    """
    falhas = []
    for pasta in _pastas_alvo():
        for item in _itens(pasta):
            try:
                if os.path.isdir(item) and not os.path.islink(item):
                    shutil.rmtree(item)
                else:
                    os.remove(item)
            except OSError:
                falhas.append(item)

    history._salvar_lista([])  # zera histórico e estatísticas do painel  # pylint: disable=protected-access
    recuperacao.descartar()  # descarta a recuperação pendente, se houver

    if app is not None:
        with app._lock_progresso:  # pylint: disable=protected-access
            app.progresso_atual = 0.0
            app.concluidos_atual = 0
            app.total_atual = 0
            app.contagem_sucesso = 0
            app.contagem_erro = 0
            app.ras_em_processamento = {}
            app.inicio_execucao_dt = None
            app.apelidos_execucao_atual = []

    if falhas_out is not None:
        falhas_out.extend(falhas)
    return len(falhas)


def zerar_painel_com_confirmacao(app):
    """Fluxo completo do botão: recusa se houver execução rodando, pede
    confirmação (listando o que será apagado), zera tudo, limpa a base
    selecionada na tela Execuções, atualiza Início e Execuções e avisa se
    houve itens que não deu pra apagar."""
    from tkinter import messagebox  # import tardio: só a interface precisa de tkinter

    if app.em_execucao:
        messagebox.showwarning(
            "Atenção", "Espere a execução atual terminar (ou clique em Parar) antes de zerar o painel."
        )
        return

    r = resumo()
    confirmar = messagebox.askyesno(
        "Zerar painel",
        "Isso vai APAGAR, sem possibilidade de desfazer:\n\n"
        f"  • os números e o histórico do painel ({r['execucoes_historico']} execução(ões));\n"
        f"  • todas as pastas de saída com os arquivos CSV e Excel ({r['pastas_saida']} pasta(s));\n"
        "  • os prints de erro e as bases de reprocessamento;\n"
        "  • o conteúdo da tela de Logs.\n\n"
        "Os perfis e os logins NÃO são apagados.\n\n"
        "Copie antes os arquivos que ainda precisar. Quer zerar mesmo assim?",
        icon="warning", default="no",
    )
    if not confirmar:
        return

    falhas = []
    n_falhas = zerar_tudo(app, falhas_out=falhas)

    # limpa a base escolhida na tela Execuções e o texto da tela de Logs
    pagina_exec = app.paginas["Execuções"]
    pagina_exec.caminho_arquivo_ras = None
    pagina_exec.label_arquivo.configure(text="Nenhum arquivo importado.", text_color=estilo.TEXTO_SECUNDARIO)
    app.paginas["Logs"]._limpar()  # pylint: disable=protected-access
    app._log(f"Painel zerado ({n_falhas} item(ns) não puderam ser apagados).")  # pylint: disable=protected-access

    for nome in ("Início", "Execuções"):
        app.paginas[nome].atualizar()

    if n_falhas:
        messagebox.showwarning(
            "Painel zerado, com ressalvas",
            f"{n_falhas} item(ns) não puderam ser apagados — provavelmente estão abertos no Excel ou no "
            "Explorer. Feche-os e use \"Zerar painel\" de novo.\n\n"
            + "\n".join(os.path.basename(f) for f in falhas[:8]),
        )
    else:
        messagebox.showinfo("Painel zerado", "Tudo limpo. Pode começar o próximo polo.")
