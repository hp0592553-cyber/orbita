# Registro abrangente de erros no Orbita (Xenon ELF)

Implementado no cliente nativo em `source/login/xc_errorlog.c`. Ao compilar
`app/h264play`, o arquivo é incluído automaticamente em `h264play.elf32`.
Não é uma alteração feita em um arquivo ELF binário já compilado.

## Arquivos no pendrive FAT

- `XC360/ERRORS.TXT`: erros detectados pelo `xc_log`, com tempo desde
  o boot (milissegundos), categoria e texto abreviado.
- `XC360/ERR_OLD.TXT`: rotação de `ERRORS.TXT` quando supera 256 KiB.
- `XC360/HANG.TXT`: watchdog e exceções graves; caminho de escrita direta
  já existente, que funciona mesmo quando uma thread para.
- `XC360/NETLOG.TXT`: tráfego/diagnóstico de rede, quando ativado e
  disponível, pelo mecanismo pré-existente.
- `XC360/DIAG.TXT`: parâmetros de diagnóstico do sistema já suportados.

## Cobertura

Erros informados por `xc_log` de rede/Wi-Fi, catálogo, login, sessão,
controle, armazenamento, mídia, atualizações e travamentos. Detecta termos
como *erro*, *falha*, *timeout*, *stalled*, *invalid*, *crash* etc. A
identificação é aproximada, não uma garantia de 100%.

Para uma compilação especial que grave **todas as mensagens `xc_log`**,
incluindo avisos e eventos comuns, use `make ... ERRORLOG_ALL=1` (precisa
de recompilação limpa para alterar o define). O padrão é
`ERRORLOG_ALL=0` para limitar desgaste/latência do USB.

## Segurança de execução

`xc_error_capture` somente copia uma linha para um anel de RAM (48
posições). A gravação FatFs é feita em lotes até 12 linhas pelo worker
`hw3`, no menu, com intervalo mínimo de 2 s. Não tenta gravar a cada
log na thread de rede/controle, no decoder ou em interrupções USB.

Mensagens com indicadores de credenciais são ocultadas; **não compartilhe
logs publicamente sem conferi-los**, pois dados pessoais podem aparecer
em outras mensagens. O novo arquivo é local: não há um novo endpoint de
envio de logs.

Quando não há pendrive gravável, a gravação falha e o anel em RAM pode
descartar mensagens antigas (o total perdido é sinalizado quando possível).
Travamento total, falha antes de inicializar o sistema, erros sem chamada
a `xc_log` e encerramento abrupto durante o jogo podem não ser registrados
em `ERRORS.TXT`; consulte `HANG.TXT`, `NETLOG.TXT` e UART também.

## Verificação no Xbox

1. Compilar e baixar o novo `h264play.elf32` na aba Actions do GitHub.
2. Iniciar com pendrive FAT gravável, sem remover o USB durante o teste.
3. Provocar um erro **inofensivo** de conexão ou catálogo e voltar ao menu.
4. Conferir se `XC360/ERRORS.TXT` contém o erro e a categoria esperada.
5. Em travamentos graves, conferir também `XC360/HANG.TXT`.
6. Testar se analógicos e botões continuam respondendo durante a sessão.

O registro ajuda a identificar e localizar falhas; não as corrige sozinho.
