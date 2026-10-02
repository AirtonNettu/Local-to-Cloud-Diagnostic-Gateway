# ADR-005: Fila de sincronização offline

> Idioma: Português (Brasil) · [English](ADR-005-offline-sync-queue.md)

Status: aceito.

## Context

Como os diagnósticos rodam offline (ADR-001), os resultados devem sobreviver a
longas quedas e chegar à nuvem exatamente uma vez quando a conectividade voltar,
sem um laço ocupado e sem perder ou duplicar eventos.

## Decision

Persistir cada evento em uma tabela `sync_queue` com uma máquina de estados
explícita: `PENDING → SYNCING → (SYNCED | FAILED | DEAD_LETTER)`. Um ciclo de
sincronização reivindica eventos devidos, entrega lotes empacotados por bytes e
registra toda tentativa em `sync_attempts`. Requisições entregues-mas-falhas
aplicam backoff (exponencial com jitter) e vão para dead-letter em `RETRY_LIMIT`.
Uma requisição que comprovadamente não foi entregue é registrada como uma
tentativa `OFFLINE` e **não** consome o orçamento de retentativas, de modo que
estar offline — a condição normal do produto — nunca manda um evento para
dead-letter. A agressividade durante uma queda é limitada pela cadência do ciclo
(uma tentativa de conexão por ciclo, sem laço de retentativa dentro do processo).

## Alternatives

- **Contar ciclos offline contra o limite de retentativas**: mandaria eventos
  para dead-letter durante quedas normais, derrotando o propósito. Rejeitado.
- **Um laço de retentativa dentro do processo**: martela a rede e a API durante
  uma queda. Rejeitado em favor de tentativas por ciclo.
- **Um broker externo (SQS no dispositivo)**: adiciona uma dependência e um
  requisito de rede a uma fila local. Rejeitado.

## Consequences

- Eventos nunca são perdidos durante uma queda e a sincronização retoma
  automaticamente.
- Um `API_BASE_URL` mal configurado que não resolve mantém eventos PENDING para
  sempre em vez de dead-letter; `status` torna isso visível (veja
  [troubleshooting.pt-BR.md](../troubleshooting.pt-BR.md)).
- A recuperação de travamento reivindica leases `SYNCING` expirados como
  tentativas `INTERRUPTED`.
