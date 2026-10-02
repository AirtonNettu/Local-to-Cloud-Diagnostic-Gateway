# Solução de problemas

> Idioma: Português (Brasil) · [English](troubleshooting.md)

## Primeiras verificações de implantação (não verificáveis offline)

Estas três só falham contra uma conta AWS real, então verifique-as primeiro
quando uma implantação nova se comporta mal:

1. **KMS AccessDenied na descriptografia de SSM SecureString.** As funções leem
   as duas chaves com `GetParameters(WithDecryption=True)`, que precisa de decrypt
   do KMS na chave gerenciada `alias/aws/ssm`. Um `KMS AccessDeniedException`
   (apresentado como um 503 pela API) significa que a política da chave ou a role
   não tem esse grant de decrypt.
2. **`sam build` não consegue resolver `CodeUri: ../src`.** O SAM resolve
   `CodeUri` relativo ao diretório do template. Rode `sam build` a partir de
   `infrastructure/` (ou passe `-t infrastructure/template.yaml`) para que
   `../src` aponte para a raiz do pacote. Isso não é testável aqui porque a SAM
   CLI não está instalada.
3. **Permissão do log de acesso do HTTP API.** Habilitar logs de acesso exige que
   o API Gateway crie uma service-linked role para
   `ops.apigateway.amazonaws.com`, que precisa de `iam:CreateServiceLinkedRole`
   para esse principal de serviço na identidade que implanta. Sem isso, a primeira
   implantação falha ao anexar o destino do log de acesso ao stage.

## Problemas de runtime do agente

- **Sincronização desativada.** `status` mostra sincronização desativada quando
  `API_BASE_URL` ou `AGENT_API_KEY` está vazio. Defina ambos em `.env`; os
  comandos locais funcionam de qualquer forma.
- **Qual `.env` foi carregado.** A ordem de busca é `--env-file PATH` → `./.env`
  → `<data dir>/.env`. `status` imprime o caminho escolhido (nunca o conteúdo) ou
  "none". Um `run` agendado começando em um diretório de trabalho diferente pode
  escolher um arquivo diferente do esperado.
- **401 Unauthorized.** A chave está ausente ou errada, ou tem o escopo errado
  para a rota (uma chave `read` em uma rota de ingestão é 403). Verifique
  `AGENT_API_KEY`.
- **`CONFIG_ERROR` e o ciclo aborta.** `API_BASE_URL` aponta para algo que
  redireciona ou retorna um status inesperado. Configure a URL HTTPS final; o
  agente nunca segue redirecionamentos, então a chave nunca é enviada ao destino.
- **Eventos presos em PENDING, tentativas offline acumulando.** Se `API_BASE_URL`
  nomeia um host que não resolve, todo ciclo é offline, então os eventos ficam
  PENDING com `attempt_count = 0` em vez de ir para dead-letter. `status` mostra a
  última tentativa como `OFFLINE (…)`. Corrija o hostname; a sincronização retoma
  automaticamente.
- **Avisos `CLOCK_SKEW`.** O relógio do agente está mais de cinco minutos
  adiantado em relação ao servidor; aquele evento é tratado como transitório e
  retentado. Corrija o relógio local (ative a sincronização de hora).
- **Banco de dados travado.** Outro processo detém o lock de escrita do SQLite. A
  execução ainda imprime seu relatório e sai 1 com `event=storage_error`; tente de
  novo quando o outro processo liberar o lock.
- **"database needs migration" em um comando somente leitura.** Comandos somente
  leitura nunca migram. Rode um comando de escrita (`scan`) uma vez para aplicar a
  migração, ou o schema é mais antigo que esta build (`SchemaOutdatedError`).
- **PowerShell bloqueado pela política de execução.** As consultas CIM somente
  leitura rodam PowerShell; uma política restritiva faz esses campos ficarem
  "unavailable" (a execução continua). Permita que o usuário atual rode scripts
  assinados/locais se você precisar de dados de GPU, gateway/DNS ou saúde de
  disco.
- **Novo device id após apagar o banco.** A identidade vive no banco. Se você
  apagar `agent.db`, uma nova identidade UUIDv4 é gerada. Defina `DEVICE_ID` em
  `.env` para fixar uma identidade estável entre resets.
- **WMI / CIM indisponível.** Quando as consultas de plataforma falham, as seções
  de GPU, gateway/DNS e disco físico mostram "unavailable" e o exit code
  permanece 0; o restante dos diagnósticos não é afetado.
