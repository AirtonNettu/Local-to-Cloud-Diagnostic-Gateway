# Observabilidade

> Idioma: Português (Brasil) · [English](observability.md)

Ambos os lados emitem um objeto JSON por linha de log. Segredos são redigidos e
objetos arbitrários nunca são serializados.

## Campos de log

O `JsonFormatter` emite `timestamp` (ISO UTC), `level`, `component` (nome do
logger), `event`, `message` e chaves de contexto da lista branca retiradas de
`extra=`:

| Campo | Significado |
|---|---|
| `device_id` | o dispositivo ao qual a linha de log se refere |
| `request_id` | id de requisição do API Gateway / id de requisição do Lambda (nuvem) |
| `run_id` | id da execução de diagnóstico |
| `event_id` | id do evento de sincronização |
| `http_status` | status para uma linha relacionada à API |
| `duration_ms` | duração da operação onde medida |
| `error`, `error_type` | resumo do erro (nunca um segredo) |
| contagens | tamanhos de lote e contadores similares |

Um filtro de redação descarta qualquer chave extra que case com
`key|token|secret|password|authorization`. O agente escreve um arquivo JSON
rotativo (`agent.log`) e um resumo curto em texto no stderr; a nuvem escreve JSON
no stdout, que o Lambda envia aos CloudWatch Logs.

## Catálogo de métricas (EMF)

As métricas da nuvem usam o Embedded Metric Format no namespace
`DiagnosticGateway` com um único conjunto de dimensões `[["Service",
"Function"]]`. `device_id` deliberadamente nunca é uma dimensão (alta
cardinalidade, custo).

| Métrica | Emitida quando |
|---|---|
| `DeviceRegistered` | um registro/atualização de dispositivo tem sucesso |
| `TelemetryAccepted` | um evento é armazenado pela primeira vez |
| `TelemetryDuplicate` | um evento é um duplicata |
| `TelemetryRejected` | um evento é rejeitado (validação / conflito) |
| `ValidationError` | uma requisição falha na validação / é malformada / grande demais |
| `AuthFailure` | um 401 ou 403 |
| `DynamoDBError` | um erro de cliente/throttling do DynamoDB |
| `LambdaError` | uma exceção inesperada no handler (mapeada para 500) |

O EMF transforma uma linha de log em métrica sem uma chamada de API separada. As
métricas customizadas são cobradas por nome × dimensão por mês (veja
[cost.pt-BR.md](cost.pt-BR.md)).

## Separação de falha de sincronização no lado do agente

O agente distingue dois tipos de falha de sincronização para que uma queda não
seja tratada como uma falha de servidor:

- **Offline** (`ConnectivityError` → tentativa `OFFLINE`): a requisição
  comprovadamente não foi entregue (falha de DNS, conexão recusada, rede
  inalcançável, timeout de conexão, interceptação de TLS). O evento continua
  PENDING/FAILED com sua contagem de tentativas e `next_attempt_at` inalterados; o
  ciclo aborta com `aborted="offline"` e loga `event=sync_offline`. Essas
  tentativas nunca consomem `RETRY_LIMIT`.
- **Entregue-mas-falhou** (`TransientSyncError` / 5xx do servidor / 429 /
  resposta malformada / entrega-incerta): a requisição foi (ou pode ter sido)
  enviada. O evento vai para FAILED com backoff e alcança DEAD_LETTER em
  `RETRY_LIMIT`.

Toda tentativa é registrada em `sync_attempts` com seu `outcome` (`ACCEPTED`,
`DUPLICATE`, `REJECTED`, `TRANSIENT_ERROR`, `OFFLINE`, `AUTH_ERROR`,
`CONFIG_ERROR`, `INTERRUPTED`), de modo que `queue` e `status` possam explicar
exatamente por que um evento não sincronizou.
