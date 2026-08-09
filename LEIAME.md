# Captura Link de Pagamento

Automação em Python (Selenium + interface gráfica) para consultar RAs de
alunos no CRM Dynamics, verificar a mensalidade do mês/ano escolhido e
capturar o link de pagamento, exportando tudo para CSV e Excel.

## Como instalar

1. Instale o Python 3.10+ (https://www.python.org/downloads/).
2. Instale o Google Chrome, se ainda não tiver.
3. Abra um terminal na pasta do projeto e rode:
   ```
   pip install -r requirements.txt
   ```

## Como usar

A interface é organizada em páginas, acessíveis pela barra lateral:

- **Início** — painel geral: total de dados capturados, execuções de
  hoje, execução em andamento e as últimas execuções.
- **Perfis** — até 3 logins independentes do Chrome, cada um com:
  - **apelido editável** (clique no nome para renomear);
  - **status de login** com detecção automática best-effort (botão
    "Verificar login" — abre o CRM em segundo plano e verifica pelos
    elementos de cabeçalho do Office 365/Dynamics; pode dar "Não foi
    possível verificar" se a tela mudar, o que não é um erro crítico);
  - **"Login manual"** — abre uma janela do Chrome para logar naquele
    perfil especificamente;
  - **"Limpar perfil"** — apaga a sessão só daquele perfil, sem afetar
    os outros dois.
- **Execuções** — importe a base de RAs, escolha o mês/ano, marque quais
  perfis vão trabalhar (qualquer combinação entre os 3 — 1, 2 ou os 3 ao
  mesmo tempo) e clique em **"Importar"** para iniciar. **"Parar"**
  interrompe a execução em andamento. O histórico completo fica
  registrado, com os apelidos dos perfis usados em cada execução.
- **Configurações** — tema claro/escuro e local dos dados.
- **Logs** — acompanhamento detalhado, linha a linha.
- **Suporte** — telefone, e-mail e botão **"Abrir manual"** (abre o
  manual completo em Word, incluído no projeto).
- **Sobre** — informações do aplicativo.

### Passo a passo rápido
1. Rode `python main.py`.
2. Vá em **Perfis** e, para cada perfil que for usar, clique em
   **"Login manual"**, faça login e feche a janela (dê um apelido antes
   ou depois, como preferir).
3. Vá em **Execuções** → **"Importar base..."** → selecione o mês/ano →
   marque os perfis → **"Importar"**.
4. Acompanhe pelo **Início** ou **Logs**. Pode interromper a qualquer
   momento com **"Parar"**.
5. Os arquivos CSV e Excel ficam em
   `Documentos/CapturaLinkPagamento/saida/` (ou na pasta alternativa,
   caso a pasta Documentos não esteja disponível) — cada execução fica
   registrada e consultável na página **Execuções**.

## Estrutura de pastas (importante manter junto)

```
main.py
app_gui.py
config.py
estilo.py
history.py
perfis.py
runner.py
crm_client.py
browser_manager.py
data_io.py
requirements.txt
LEIAME.md
assets/
  icone.ico
  logo.png
  manual.docx
paginas/
  __init__.py
  pagina_inicio.py
  pagina_execucoes.py
  pagina_perfis.py
  pagina_configuracoes.py
  pagina_logs.py
  pagina_suporte.py
  pagina_sobre.py
```

## ⚠️ Pontos que precisam de confirmação antes do primeiro uso real

O briefing original não trouxe o HTML completo de duas partes da tela,
então usei estimativas que **precisam ser confirmadas/ajustadas** em
`config.py`:

1. **Aba "Cadastro"** (CPF, Nome, Sobrenome, E-mail, Curso): nomes
   lógicos em `config.CAMPOS_CADASTRO` são estimativas.
2. **Grade "Todos os Extratos"**: faltam os `col-id` reais de "Data
   pagamento", "Valor Pago", "Meio de pagamento", "Status da fatura" e
   "Origem" (`config.COL_DATA_PAGAMENTO` etc., hoje `None`).

Veja instruções de como descobrir esses valores nos comentários do
próprio `config.py`.

## O que ainda falta / observações

- **Testar contra o ambiente real**: nunca foi executado contra o CRM de
  verdade. É esperado precisar de pequenos ajustes de tempo de espera
  (`config.TIMEOUT_PADRAO`) e seletores após o primeiro teste real —
  incluindo a **detecção de login** (best-effort, em `browser_manager.
  detectar_login`), que depende de a URL não mudar de padrão.
- O **manual em Word** (`assets/manual.docx`) tem instruções completas de
  uso, mas ainda **não tem capturas de tela reais** da interface — foi
  gerado sem acesso a um ambiente gráfico de teste. Posso adicionar
  screenshots reais assim que houver a possibilidade de gerá-las.
- O botão "Abrir manual" já está preparado para funcionar tanto rodando
  com `python main.py` quanto num futuro `.exe` empacotado com
  PyInstaller (usa `sys._MEIPASS` quando aplicável) — mas o projeto
  atual continua sendo entregue como `.py` puro, conforme definido.

## Suporte
(11) 94727-8128 — samueldayvid5@icloud.com
