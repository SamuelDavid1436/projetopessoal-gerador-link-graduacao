# Captura Link de Pagamento

Automação para consultar alunos no CRM Dynamics (Kroton/Anhanguera),
verificar a situação financeira e gerar o link de pagamento das
mensalidades em aberto — em lote, a partir de uma planilha de RAs, com
interface gráfica própria e sem precisar tocar no CRM manualmente.

![Tela Início](docs/screenshots/inicio.png)

## Índice

- [O que o programa faz](#o-que-o-programa-faz)
- [Funcionalidades](#funcionalidades)
- [Capturas de tela](#capturas-de-tela)
- [Instalação (uso final — sem Python)](#instalação-uso-final--sem-python)
- [Instalação (desenvolvimento)](#instalação-desenvolvimento)
- [Como usar](#como-usar)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Gerando o executável (.exe)](#gerando-o-executável-exe)
- [Solução de problemas comuns](#solução-de-problemas-comuns)
- [Suporte](#suporte)

## O que o programa faz

Você importa uma planilha (CSV ou Excel) com uma coluna de RAs. Pra cada
RA, a automação:

1. Busca o aluno no CRM.
2. Confere o cadastro (nome completo, CPF, celular, e-mail, curso).
3. Verifica a situação financeira (Adimplente/Inadimplente).
4. Checa a mensalidade do mês seguinte primeiro; se não estiver
   disponível, avalia a do mês vigente.
5. Se a fatura já estiver **paga** ou **negociada**, só traz os dados —
   não gera link. Caso contrário, gera o link de pagamento.
6. Registra tudo (inclusive erros) numa planilha de saída.

Cada execução é **independente**: não existe histórico de "RA já
processado" travando nada — a mesma base pode ser reimportada quantas
vezes for preciso ao longo do mês, atualizando quem ainda não pagou.

## Funcionalidades

- **Até 3 perfis de login independentes**, rodando em paralelo (cada
  janela do Chrome com sua própria sessão) — apelido editável, e-mail
  detectado automaticamente (ou editável na mão), verificação de login,
  limpar perfil.
- **Painel de acompanhamento em tempo real**: progresso, previsão de
  término, Processados/Sucessos/Pendentes/Erros.
- **Reinício automático do navegador** se a sessão do Chrome morrer no
  meio de uma execução (crash, falta de memória, etc.) — sem isso, todo
  RA restante falharia em cascata; com isso, só reinicia e continua de
  onde parou.
- **Botão "Reprocessar erros"** no histórico — gera automaticamente uma
  nova base só com os RAs que deram erro numa execução, pronta pra
  reimportar.
- **Log de retomada**: se o programa cair no meio de uma execução
  (queda de energia, travamento), oferece recuperar os resultados
  parciais já capturados ao reabrir.
- **Screenshot automático** de qualquer erro, salvo com data/hora, pra
  facilitar diagnóstico.
- **Cada execução gera sua própria pasta** de saída (CSV + Excel),
  identificada por data/hora — nunca mistura arquivos de execuções
  diferentes.
- **Manual do usuário completo**, embutido no programa (aba Suporte).

## Capturas de tela

| Início (execução em andamento) | Execuções | Perfis |
|---|---|---|
| ![Execução em andamento](docs/screenshots/inicio_executando.png) | ![Execuções](docs/screenshots/execucoes.png) | ![Perfis](docs/screenshots/perfis.png) |

## Instalação (uso final — sem Python)

Se você só vai **usar** o programa (não desenvolver), não precisa
instalar Python nem nada disso — só:

1. Google Chrome instalado.
2. Conexão com a internet.
3. O executável `CapturaLinkPagamento.exe` (peça pra quem gera os
   builds, ou veja [Gerando o executável](#gerando-o-executável-exe)).

Na primeira vez que abrir numa máquina nova, pode ser necessário
liberar o certificado da empresa — veja `TI_LEIA_ISTO.md` e
`instalar_certificado.ps1` na raiz do projeto.

## Instalação (desenvolvimento)

```bash
git clone <url-deste-repositório>
cd CapturaLinkPagamento
pip install -r requirements.txt
python main.py
```

Requer Python 3.10+ e Google Chrome. O `webdriver-manager` cuida de
baixar a versão certa do ChromeDriver automaticamente na primeira
execução.

## Como usar

A interface é organizada em páginas, acessíveis pela barra lateral:

- **Início** — painel geral: dados capturados, perfis configurados,
  execuções de hoje, e o acompanhamento ao vivo de uma execução em
  andamento (progresso, previsão de término, métricas).
- **Perfis** — configure até 3 logins independentes do Chrome:
  - **Login manual** — abre uma janela do Chrome pra logar naquele
    perfil especificamente; o e-mail é detectado automaticamente.
  - **Verificar login** — checa rapidamente se o perfil ainda está
    autenticado no CRM.
  - **✎ (lápis)** — edita o apelido ou o e-mail manualmente, caso a
    detecção automática não funcione.
  - **Limpar perfil** — apaga login, apelido e e-mail só daquele
    perfil, sem afetar os outros.
- **Execuções** — importe a base de RAs, marque quais perfis vão
  trabalhar (qualquer combinação entre os 3) e clique em **Importar**.
  **Parar** interrompe a execução — sem fechar o navegador no meio de
  um RA. O histórico completo fica registrado, com botões **Abrir
  pasta** e **Reprocessar erros** por execução.
- **Configurações** — tema claro/escuro e local dos dados.
- **Logs** — acompanhamento detalhado, linha a linha, em tempo real.
- **Suporte** — telefone, e-mail e botão **Abrir manual** (manual
  completo em PDF, com todas as telas explicadas).
- **Sobre** — versão do aplicativo.

### Passo a passo rápido

1. Abra o programa.
2. Vá em **Perfis** e, pra cada perfil que for usar, clique em **Login
   manual**, faça o login e feche a janela.
3. Vá em **Execuções** → **Importar base...** → selecione o arquivo →
   marque os perfis → **Importar**.
4. Acompanhe pela tela **Início** ou **Logs**. Pode interromper a
   qualquer momento com **Parar**.
5. Ao final, o programa oferece abrir a pasta com os arquivos de
   resultado (CSV + Excel).

## Estrutura do projeto

```
CapturaLinkPagamento/
├── main.py                    # ponto de entrada
├── app_gui.py                 # controlador principal da interface
├── crm_client.py              # toda a interação Selenium com o CRM
├── runner.py                  # orquestração dos perfis em paralelo
├── browser_manager.py         # gestão de perfis do Chrome e detecção de login
├── perfis.py                  # metadados dos perfis (apelido, e-mail, status)
├── history.py                 # histórico de execuções
├── recuperacao.py             # log de retomada em caso de queda
├── data_io.py                 # leitura de RAs e gravação dos resultados
├── config.py                  # seletores, caminhos, constantes gerais
├── estilo.py                  # paleta de cores e tema
├── paginas/                   # cada tela da interface
├── assets/                    # ícone, logo, manual (Word + PDF)
├── requirements.txt
├── CapturaLinkPagamento.spec  # configuração do PyInstaller
├── build_exe.bat              # gera e assina o .exe (Windows)
├── gerar_certificado.ps1      # gera o certificado de assinatura (uma vez)
├── assinar_exe.ps1            # assina o .exe (chamado pelo build_exe.bat)
├── instalar_certificado.ps1   # roda em cada máquina final, uma vez
├── LEIAME.md
├── LEIAME_EMPACOTAMENTO.md    # como gerar o .exe, passo a passo
└── TI_LEIA_ISTO.md            # guia pro TI liberar o certificado
```

## Gerando o executável (.exe)

O PyInstaller não faz build cruzado — o `.exe` precisa ser gerado numa
máquina **Windows**. Resumo (detalhes completos em
`LEIAME_EMPACOTAMENTO.md`):

```
build_exe.bat
```

Isso instala as dependências, gera o `.exe` em `dist\` e já assina com
o certificado da empresa, se ele existir (`gerar_certificado.ps1` — só
precisa rodar uma vez, na vida do projeto).

Antes de distribuir pra qualquer máquina nova, rode
`instalar_certificado.ps1` nela (uma vez), pra evitar o aviso de
"arquivo bloqueado" do Windows. Veja `TI_LEIA_ISTO.md` para o guia
completo, incluindo o que fazer se a empresa usar AppLocker/WDAC.

## Solução de problemas comuns

**"Chrome failed to start: crashed" / perfil perde o login do nada**
Quase sempre é a pasta de perfis do Chrome estar dentro de uma pasta
sincronizada por OneDrive/Google Drive — o sincronizador brigando com o
Chrome pelos mesmos arquivos causa corrupção. Este projeto já guarda os
perfis em `%LOCALAPPDATA%` (fora de qualquer sincronização) por esse
motivo exato.

**"invalid session id" em cascata (todo RA seguinte falha igual)**
Sinal de que a sessão do navegador morreu de vez no meio da execução —
o programa detecta isso automaticamente e reinicia o navegador sozinho,
continuando a partir do próximo RA (até 3 tentativas seguidas antes de
desistir daquele perfil).

**Windows bloqueia o `.exe` ("política de Controle de Aplicativo")**
Veja `TI_LEIA_ISTO.md` — geralmente é o certificado não instalado
(`instalar_certificado.ps1`) ou o Controle Inteligente de Aplicativos
do Windows 11 ativado (Configurações → Privacidade e segurança →
Segurança do Windows → Controle de aplicativos e do navegador).

**Campo vem em branco no resultado**
A coluna "Status da Consulta" mostra um aviso (`AVISO: campo(s) vazio(s)
- ...`) quando isso acontece mesmo sem erro explícito — vale conferir
esse RA manualmente no CRM.

## Suporte

Contato disponível dentro do próprio programa, na aba **Suporte** — ou
consulte o manual completo (Word/PDF) em `assets/manual.pdf`.
