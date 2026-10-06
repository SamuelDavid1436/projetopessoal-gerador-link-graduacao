# -*- coding: utf-8 -*-
"""
limpeza.py
==========
Lógica do botão "Zerar painel": apaga o histórico de execuções (números do
painel), as pastas de saída (CSV/Excel), os prints de erro, as bases de
reprocessamento e o log de retomada.

NÃO mexe nos perfis do Chrome (logins), nos apelidos/e-mails dos perfis, nem
em nenhum arquivo fora das pastas do programa em Documentos.
"""
import os
import shutil

import config
import history
import recuperacao


def _pastas_alvo() -> list:
    """Pastas cujo CONTEÚDO é apagado (as pastas em si são mantidas)."""
    return [
        config.PASTA_SAIDA,
        config.PASTA_SCREENSHOTS,
        os.path.join(config.PASTA_LOGS, "reprocessamentos"),
    ]


def _eh_pasta_segura(pasta: str) -> bool:
    """Só deixa apagar dentro da pasta de dados do programa (Documentos/
    CapturaLinkPagamento) — e nunca ela própria. Trava de segurança contra
    caminho errado."""
    base = os.path.realpath(config.PASTA_DOCUMENTOS)
    alvo = os.path.realpath(pasta)
    try:
        return os.path.commonpath([base, alvo]) == base and alvo != base
    except ValueError:  # discos diferentes no Windows
        return False


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


def zerar_tudo() -> dict:
    """Apaga tudo. Devolve {"removidos": n, "falhas": [caminhos que não deu pra apagar]}.
    Arquivo aberto no Excel, por exemplo, não pode ser apagado no Windows —
    fica na lista de falhas e o resto segue sendo apagado."""
    removidos, falhas = 0, []
    for pasta in _pastas_alvo():
        for item in _itens(pasta):
            try:
                if os.path.isdir(item) and not os.path.islink(item):
                    shutil.rmtree(item)
                else:
                    os.remove(item)
                removidos += 1
            except OSError:
                falhas.append(item)

    history._salvar_lista([])  # zera os números do painel
    recuperacao.descartar()  # descarta log de retomada, se houver
    return {"removidos": removidos, "falhas": falhas}
