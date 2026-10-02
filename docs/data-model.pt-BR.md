# Modelo de dados

> Idioma: Português (Brasil) · [English](data-model.md)

Dois armazenamentos: o design de tabela única no DynamoDB na nuvem e o banco
SQLite local.

## Tabela única do DynamoDB

Uma tabela (`${StackName}-diagnostics`), cobrança sob demanda, um GSI1 esparso e
um atributo de TTL. Perfis de dispositivo e eventos de diagnóstico compartilham
uma partição por dispositivo.

Chaves e atributos:

- `PK` (S): `DEVICE#<device_id>` para ambas as entidades.
- `SK` (S): `PROFILE` para o perfil do dispositivo; `DIAG#<event_id>` para um
  evento. Como `event_id` é um UUIDv7 (ordenado por tempo), a sort key é
  naturalmente cronológica, então "mais novos primeiro" é um `Query` reverso.
- `GSI1PK` / `GSI1SK` (S): apenas perfis os carregam (`GSI1PK = DEVICE`,
  `GSI1SK = DEVICE#<device_id>`), tornando o GSI1 esparso para que "listar
  dispositivos" varra apenas perfis.
- `expires_at` (N, segundos epoch): TTL nos eventos de diagnóstico (padrão 30
  dias).

Padrões de acesso:

| ID | Pergunta | Operação |
|---|---|---|
| AP1 | registrar / atualizar um dispositivo | `UpdateItem` em `(PK, PROFILE)`, idempotente |
| AP2 | ler um dispositivo | `GetItem` em `(PK, PROFILE)` |
| AP3 | listar dispositivos | `Query` no GSI1 `GSI1PK = DEVICE`, paginado |
| AP4 | ingerir um evento | `PutItem` condicional (`attribute_not_exists(PK)`) |
| AP5 | diagnósticos recentes | `Query` `PK = DEVICE#id AND begins_with(SK, 'DIAG#')`, reverso |
| AP6 | atualizar último status | `UpdateItem` guardado por `latest_event_id < :eid` |
| AP6b | avançar `last_seen_at` | `UpdateItem` com `attribute_exists(PK)` |

Idempotência: o put condicional armazena um `payload_sha256`. Um `event_id`
reusado com o mesmo payload é um `duplicate` (um item armazenado); um id reusado
com payload diferente é `EVENT_ID_CONFLICT` (rejeitado). A cobrança sob demanda
evita planejamento de capacidade para uma carga esporádica e de baixo volume; o
TTL expira eventos antigos de graça; point-in-time recovery fica desligado por
padrão como trade-off de custo documentado.

Os campos de perfil armazenados respondidos por AP2/AP3 incluem `device_id`,
`device_name`, `os`, `hardware`, `agent_version`, `registered_at`, `updated_at`,
`last_seen_at` e o resumo `latest_*`. A API pública remove chaves internas (`PK`,
`SK`, `GSI1*`, `entity`, `payload_sha256`, `payload`) e converte números
`Decimal` do DynamoDB de volta para `int`.

## SQLite local

Modo WAL, foreign keys ativas, migrações por `PRAGMA user_version` e
`PRAGMA application_id` para distinguir bancos live de demo (para que o modo demo
nunca apague um arquivo que não criou).

- `devices` — uma identidade local (`is_local = 1`, imposta por um índice único
  parcial), overrides armazenados com `is_local = 0`; também guarda o
  fingerprint de registro usado para pular o re-registro quando nada mudou.
- `diagnostic_runs` — uma linha por execução com o `result_json` completo,
  indexado por `(device_id, started_at DESC)`.
- `diagnostic_results` — checks/alerts/metrics achatados para consulta, com o
  detalhe rico em `details_json`.
- `sync_queue` — uma linha por evento: `state`, `attempt_count`,
  `next_attempt_at`, `claimed_at`, o `payload_json` congelado e timestamps.
  `run_id` é UNIQUE para que uma execução mapeie a um evento.
- `sync_attempts` — uma auditoria somente-append de toda tentativa de entrega com
  `outcome`, `http_status`, `error_code` e tempo.

O caminho de escrita (`LocalStore.save_run`) insere a execução, seus resultados e
o evento da fila dentro de uma única transação `BEGIN IMMEDIATE`, de modo que uma
execução persistida que deve sincronizar sempre tem um evento na fila e
vice-versa.
