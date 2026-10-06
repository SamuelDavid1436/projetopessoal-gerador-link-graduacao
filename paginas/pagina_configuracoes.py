# -*- coding: utf-8 -*-
"""
paginas/pagina_configuracoes.py
=================================
Tema claro/escuro, informações de onde os dados ficam salvos e a seção
separada "Zerar painel (começar outro polo)". O conteúdo fica num frame com
rolagem, pra nada ser cortado em telas menores.
"""
import customtkinter as ctk

import config
import estilo


class PaginaConfiguracoes(ctk.CTkFrame):
    def __init__(self, master, controlador):
        super().__init__(master, fg_color="transparent")
        self.controlador = controlador

        conteudo = ctk.CTkScrollableFrame(self, fg_color="transparent")
        conteudo.pack(fill="both", expand=True)

        ctk.CTkLabel(conteudo, text="Configurações", font=ctk.CTkFont(size=24, weight="bold"),
                     text_color=estilo.TEXTO_PRIMARIO).pack(anchor="w", padx=24, pady=(24, 4))
        ctk.CTkLabel(conteudo, text="Preferências gerais do aplicativo.",
                     font=ctk.CTkFont(size=13), text_color=estilo.TEXTO_SECUNDARIO).pack(anchor="w", padx=24, pady=(0, 16))

        # --- Tema ---
        painel_tema = ctk.CTkFrame(conteudo, fg_color=estilo.FUNDO_CARTAO, corner_radius=estilo.RAIO_CARTAO)
        painel_tema.pack(fill="x", padx=24, pady=(0, 16))
        linha = ctk.CTkFrame(painel_tema, fg_color="transparent")
        linha.pack(fill="x", padx=16, pady=16)
        bloco_texto = ctk.CTkFrame(linha, fg_color="transparent")
        bloco_texto.pack(side="left")
        ctk.CTkLabel(bloco_texto, text="Tema escuro", font=ctk.CTkFont(weight="bold"),
                     text_color=estilo.TEXTO_PRIMARIO).pack(anchor="w")
        ctk.CTkLabel(bloco_texto, text="Alterna entre o tema claro e o escuro.",
                     text_color=estilo.TEXTO_SECUNDARIO).pack(anchor="w")
        self.switch_tema = ctk.CTkSwitch(linha, text="", command=self._alternar_tema,
                                         progress_color=estilo.VERDE)
        self.switch_tema.pack(side="right")
        if ctk.get_appearance_mode() == "Dark":
            self.switch_tema.select()

        # --- Onde os dados ficam ---
        painel_dados = ctk.CTkFrame(conteudo, fg_color=estilo.FUNDO_CARTAO, corner_radius=estilo.RAIO_CARTAO)
        painel_dados.pack(fill="x", padx=24, pady=(0, 16))
        ctk.CTkLabel(painel_dados, text="Onde os dados ficam salvos", font=ctk.CTkFont(weight="bold"),
                     text_color=estilo.TEXTO_PRIMARIO).pack(anchor="w", padx=16, pady=(16, 4))
        ctk.CTkLabel(painel_dados, text=config.PASTA_DOCUMENTOS, text_color=estilo.TEXTO_SECUNDARIO).pack(
            anchor="w", padx=16, pady=(0, 12)
        )
        ctk.CTkButton(
            painel_dados, text="Abrir pasta de dados", fg_color=estilo.FUNDO_SUTIL, hover_color=estilo.BORDA,
            text_color=estilo.TEXTO_PRIMARIO,
            command=lambda: self.controlador.abrir_pasta(config.PASTA_DOCUMENTOS),
        ).pack(anchor="w", padx=16, pady=(0, 16))

        # --- Seção separada: Zerar painel ---
        painel_zerar = ctk.CTkFrame(conteudo, fg_color=estilo.FUNDO_CARTAO, corner_radius=estilo.RAIO_CARTAO)
        painel_zerar.pack(fill="x", padx=24, pady=(0, 24))
        ctk.CTkLabel(painel_zerar, text="Zerar painel (começar outro polo)", font=ctk.CTkFont(weight="bold"),
                     text_color=estilo.TEXTO_PRIMARIO).pack(anchor="w", padx=16, pady=(16, 4))
        ctk.CTkLabel(
            painel_zerar,
            text=("Use entre uma execução e outra para começar do zero. Apaga os números e o histórico do "
                  "painel, todas as pastas de saída (CSV e Excel), os prints de erro, as bases de "
                  "reprocessamento e o conteúdo da tela de Logs.\n"
                  "Os perfis e os logins NÃO são apagados. Não dá para desfazer: use \"Abrir pasta Saída\" "
                  "para copiar antes os arquivos que ainda precisar."),
            text_color=estilo.TEXTO_SECUNDARIO, justify="left", wraplength=680,
        ).pack(anchor="w", padx=16, pady=(0, 12))
        linha_botoes = ctk.CTkFrame(painel_zerar, fg_color="transparent")
        linha_botoes.pack(anchor="w", padx=16, pady=(0, 16))
        ctk.CTkButton(
            linha_botoes, text="📂  Abrir pasta Saída", fg_color=estilo.FUNDO_SUTIL, hover_color=estilo.BORDA,
            text_color=estilo.TEXTO_PRIMARIO, width=170,
            command=lambda: self.controlador.abrir_pasta(config.PASTA_SAIDA),
        ).pack(side="left", padx=(0, 10))
        self.botao_zerar = ctk.CTkButton(
            linha_botoes, text="🗑  Zerar painel", fg_color=estilo.BOTAO_PARAR,
            hover_color=estilo.BOTAO_PARAR_HOVER, text_color="white", width=160,
            command=self.controlador.zerar_painel,
        )
        self.botao_zerar.pack(side="left")

    def atualizar(self):
        # não deixa zerar o painel no meio de uma execução
        self.botao_zerar.configure(state="disabled" if self.controlador.em_execucao else "normal")

    def _alternar_tema(self):
        modo = "dark" if self.switch_tema.get() else "light"
        ctk.set_appearance_mode(modo)
