# -*- coding: utf-8 -*-
"""
estilo.py
=========
Cores e constantes visuais compartilhadas por toda a interface. Usa o
padrão do customtkinter de tupla (cor_no_claro, cor_no_escuro) para que os
widgets troquem de cor automaticamente ao alternar o tema.
"""
import config

VERDE = config.COR_VERDE
VERDE_HOVER = config.COR_VERDE_ESCURO

DOURADO = config.COR_DOURADO
DOURADO_HOVER = config.COR_DOURADO_ESCURO

# fundo geral da janela / área de conteúdo
FUNDO = (config.COR_GELO, "#15151c")
# fundo da barra lateral
FUNDO_SIDEBAR = (config.COR_CREME, "#101014")
# fundo dos cartões/painéis
FUNDO_CARTAO = ("#FFFFFF", "#1e1e27")
# fundo de itens "sutis" dentro de um cartão (linhas de tabela, etc.)
FUNDO_SUTIL = ("#F4F1EE", "#26262f")

TEXTO_PRIMARIO = (config.COR_CINZA_ESCURO, "#F2F2F2")
TEXTO_SECUNDARIO = ("#8A8A8A", "#9A9AA5")

BORDA = ("#E7E1DB", "#2E2E38")

VERDE_SUCESSO = ("#1E8E5A", "#3DDC84")
VERMELHO_ERRO = ("#D64545", "#FF6B6B")
AMARELO_ALERTA = ("#B98900", "#F5C542")

BOTAO_PARAR = ("#D64545", "#B23B3B")
BOTAO_PARAR_HOVER = ("#B23B3B", "#8F2E2E")

RAIO_CARTAO = 12
