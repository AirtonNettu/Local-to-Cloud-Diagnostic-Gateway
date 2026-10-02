# Guia de Revisão e Estudo — Local-to-Cloud Diagnostic Gateway

> Idioma da documentação: [English](REVIEW_GUIDE.md) · Português (Brasil) (este arquivo)

Este é um guia técnico de revisão e estudo do projeto já finalizado. É apenas
documentação: nenhum código de produção foi alterado, nenhuma funcionalidade foi
adicionada, nenhum teste foi criado, nada foi implantado. O código e a
documentação em disco são a única fonte de verdade. Onde documentação e
implementação divergem, a divergência é registrada explicitamente (ver a seção
final, *Verificação da Fonte de Verdade*).

Como usar: leia de cima a baixo uma vez para formar o modelo mental e depois use
as seções 16–20 como trilha ativa de estudo/entrevista. Os caminhos de arquivo
são indicados para você ir direto ao código por trás de cada afirmação.

---

## 1. Project Overview

**Problema resolvido.** Diagnosticar uma máquina que está, ela mesma, com
problemas de conectividade é complicado: um agente dependente da nuvem deixa de
ser útil exatamente quando a rede degrada. Este projeto roda todos os
diagnósticos localmente e trata a nuvem como um arquivo opcional, de melhor
esforço. (`README.md`, `docs/decisions/ADR-001-local-first.md`.)

**Objetivo do sistema.** Um agente Python Windows-first coleta telemetria de
hardware, SO, armazenamento e rede, avalia regras determinísticas de saúde
localmente, persiste cada execução em SQLite e continua funcionando sem
internet. Um subconjunto minimizado e higienizado de cada execução é enfileirado
localmente e sincronizado com um backend serverless AWS (HTTP API Gateway →
Lambda → DynamoDB single-table) com uma política de retry limitada, guiada por
backoff, e ingestão exatamente-uma-vez (idempotente).

**Princípio local-first.** Diagnósticos, avaliação de saúde e persistência rodam
inteiramente no host, sem dependência de rede. Todo comando local funciona
offline. A sincronização é uma etapa separada e opcional que lê uma fila já
persistida; suas falhas nunca alteram o resultado do diagnóstico. Persistir +
enfileirar acontecem em uma única transação local *antes* de qualquer
sincronização. (`ADR-001`, `docs/architecture.md`.)

**O que funciona localmente (sem nuvem, sem rede).**
- `diagnostic-agent hardware` — inventário de hardware somente-leitura.
- `diagnostic-agent network` — coleta + classificação com evidências/causas.
- `diagnostic-agent health` — pipeline completo, sem escrita no banco.
- `diagnostic-agent scan` — pipeline completo, persiste a execução (e enfileira quando a sincronização está habilitada).
- `diagnostic-agent status` / `queue list` / `queue stats` — inspeção somente-leitura.
- `diagnostic-agent demo [--all | --scenario NAME]` — seis cenários determinísticos sobre entradas simuladas.
- `diagnostic-agent run [--iterations N]` — laço scan+sync no intervalo de telemetria.

**O que pertence à camada AWS.** O backend opcional: um HTTP API Gateway, quatro
funções Lambda (`health`, `device`, `telemetry`, `diagnostic`), uma única tabela
DynamoDB com GSI e TTL, duas chaves de API SecureString no SSM, logs CloudWatch +
métricas EMF e papéis IAM por função. Tudo declarado em
`infrastructure/template.yaml` (AWS SAM).

**Fora do escopo atual (confirmado; ver §15).** Não implantado na AWS; sem
instalador de Serviço Windows / tarefa agendada; sem execução remota de comandos;
sem dashboard web; sem alarmes SNS/CloudWatch; sem coletores Linux/macOS; sem
credenciais por dispositivo ou mTLS; execuções com sincronização desabilitada não
são preenchidas retroativamente.

---

## 2. End-to-End Architecture

O fluxo canônico (de `diagrams/architecture.mmd` / `README.md`):

```
Windows Agent → Collectors → Diagnostic Engine → SQLite → Offline Queue
   → Sync Service → HTTP(S) ApiClient → API Gateway → Lambda → DynamoDB
```

Serviços AWS transversais: **CloudWatch** (logs + métricas EMF), **SSM Parameter
Store** (duas chaves SecureString), **IAM** (um papel por função), **SAM** (o
template que declara tudo isso).

Por componente — responsabilidade, entrada, saída, dependências, comunicação,
arquivo(s):

| Componente | Responsabilidade | Entrada | Saída | Depende de | Comunica com | Arquivo(s) |
|---|---|---|---|---|---|---|
| CLI / orquestração | Parsear args, mapear exit codes, montar o pipeline | argv, `.env`, env vars | exit code, relatório | `argparse`, settings | commands → pipeline/sync | `src/agent/main.py`, `src/agent/commands.py` |
| Collectors | Ler um domínio cada (CPU/mem/storage/system/GPU/disk/network) | SO/psutil/PowerShell | dataclasses tipadas (`CpuInfo`, …) | `psutil`, módulo de plataforma | pipeline via `run_collector` | `src/agent/collectors/*`, `src/agent/collectors/base.py` |
| platform_support | CIM Windows somente-leitura via PowerShell | saída de subprocess | fatos JSON parseados | `subprocess`, PowerShell | collectors | `src/agent/platform_support/*` |
| Motor de diagnóstico | Collect → diagnose → evaluate em um `DiagnosticResult` | resultados de coletores, probes | `DiagnosticResult` (checks/alerts/metrics/facts/status) | collectors, probes, rules, thresholds | pipeline/commands | `src/agent/pipeline.py`, `src/agent/diagnostics/engine.py`, `diagnostics/network_diagnostics.py`, `diagnostics/rules.py`, `diagnostics/health.py`, `diagnostics/probes.py` |
| SQLite (LocalStore) | Persistência durável e transacional de runs/results/queue | `DiagnosticResult` | linhas em `diagnostic_runs`, `diagnostic_results`, `sync_queue` | `sqlite3`, WAL | pipeline, sync service | `src/agent/storage/local_db.py` |
| Fila offline | Dona de toda transição de estado da fila | linhas da fila, relógio | mudanças de estado, linhas em `sync_attempts` | `sqlite3`, política de backoff | sync service | `src/agent/storage/queue.py`, `src/agent/sync/retry.py` |
| Serviço de sync | Um ciclo de sync limitado: registrar, agrupar, entregar, transicionar | fila, settings, device id | `SyncReport` | queue, ApiClient, serializer, schema compartilhado | ApiClient → nuvem | `src/agent/sync/service.py` |
| Serializer | Whitelist + higienização de IP do payload enviado | `DiagnosticResult` | dict de evento/registro minimizado | `ipaddress`, modelos compartilhados | sync service | `src/agent/sync/serializer.py` |
| ApiClient / transporte | HTTP + classificação ordenada de respostas; sem redirects | dict de evento/registro | resultados tipados ou erros tipados | `urllib`, `ssl` | API Gateway | `src/agent/sync/client.py` |
| API Gateway (HTTP API v2) | Entrada pública HTTPS; rota + throttle + log de acesso | requisição HTTPS | evento proxy Lambda | — | Lambda | `infrastructure/template.yaml` (`HttpApi`) |
| Lambda × 4 | Computação stateless por rota | evento API Gateway v2 | resposta proxy | schema compartilhado, repository, auth, http | DynamoDB, SSM, CloudWatch | `src/cloud/handlers/{health,device,telemetry,diagnostic}.py`, `src/cloud/http.py` |
| Auth | Verificação de chave Bearer, dois escopos | header `Authorization` | `None` / `Unauthorized` / `Forbidden` | SSM, `hmac` | SSM | `src/cloud/auth.py` |
| Repository | Padrões de acesso DynamoDB single-table | chamadas dos handlers | itens / resultados DynamoDB | `boto3` | DynamoDB | `src/cloud/repository.py`, `src/cloud/cursor.py` |
| DynamoDB | Store durável e idempotente (perfis + eventos) | PutItem/GetItem/Query/UpdateItem | itens, expiração TTL | — | repository | `infrastructure/template.yaml` (`DiagnosticsTable`) |
| CloudWatch | Logs + métricas custom EMF | JSON em stdout / linhas EMF | métricas, log groups | — | todas as Lambdas | `src/cloud/metrics.py`, `src/shared/utils/json_logging.py`, log groups do template |
| SSM Parameter Store | Guarda as duas chaves SecureString | `GetParameters` | valores de chave descriptografados | KMS `alias/aws/ssm` | auth | parâmetros do template + `DeviceRole`/`TelemetryRole`/`DiagnosticRole` |
| IAM | Papel de menor privilégio por função | — | permissões escopadas | — | serviços AWS | papéis em `infrastructure/template.yaml` |
| SAM | Declara todo o backend como código | parâmetros | stack CloudFormation | CloudFormation | todos os recursos AWS | `infrastructure/template.yaml`, `infrastructure/samconfig.toml` |

Fatos de comunicação para memorizar: o agente fala **HTTPS JSON com token Bearer
e recusa redirects**; o validador compartilhado em `src/shared/schemas` é o
**contrato usado pelos dois lados** (o agente pré-valida cada evento com o mesmo
código que a nuvem aplica); o bundle da Lambda é **apenas stdlib + boto3** (um
teste de limite de import mantém o código do agente dependente de `psutil` fora
de `cloud`).

---

## 3. Repository Map

Apenas arquivos arquiteturalmente importantes. Para cada um: caminho ·
responsabilidade · por que existe · quem chama · o que chama · conceitos técnicos.

**Entrada e orquestração do agente**
- `src/agent/main.py` — montagem do argparse + política de exit code (0 ok, 1 erro, 2 uso/config, 3 sync incompleta, 130 interrupção). Existe para manter `main` enxuto. Chamado pelo console script `diagnostic-agent` / `python -m agent`. Chama `commands.*`. Conceitos: design de CLI, exit codes.
- `src/agent/commands.py` — um handler por subcomando; abre/fecha o banco, resolve identidade, roda pipeline/sync. Existe para que cada comando seja testável. Chamado por `main`. Chama `pipeline`, `storage`, `sync` (de forma lazy). Conceitos: ciclo de vida de recursos, precedência de exit (1 > 3 > 0), imports lazy para o limite local-first.
- `src/agent/pipeline.py` — `DiagnosticPipeline.run`: collect → diagnose → evaluate → (persist + enqueue). Existe para tornar os provedores injetáveis (demo/testes trocam por simulados). Chamado por `commands`, `demo`. Chama coletores, `NetworkDiagnostics`, `evaluate_result`, `LocalStore.save_run`. Conceitos: injeção de dependência, Protocols, verificação de invariante via `ValueError` explícito.
- `src/agent/identity.py` — `resolve_device_id`: identidade UUIDv4 com uma única linha `is_local=1`, ou override `DEVICE_ID` (`is_local=0`). Chamado por `commands`, sync. Chama `sqlite3`. Conceitos: identidade estável desacoplada de IP/seriais, índice único parcial.

**Diagnóstico**
- `src/agent/diagnostics/engine.py` — `collect_all` / `diagnose` / `evaluate_result`; monta métricas (descarta `None`). Somente-leitura; nunca importa `sync`. Conceitos: separação coleta vs avaliação.
- `src/agent/diagnostics/network_diagnostics.py` — probing de gateway/internet/DNS + classificação first-match (UNKNOWN/OFFLINE/UNSTABLE/DEGRADED/HEALTHY). Regra de privacidade chave: **evidência refere-se a interfaces apenas por contagem, nunca por nome**. Conceitos: classificação de rede, taxa-de-falha-de-probe-TCP como "packet loss".
- `src/agent/diagnostics/probes.py`, `rules.py`, `health.py`, `facts.py` — primitivas de probe, regras determinísticas de threshold, agregação de saúde, dicionário de fatos.

**Coletores / plataforma**
- `src/agent/collectors/base.py` — `run_collector`: o limite de isolamento; qualquer falha de coletor vira um status de `CollectorResult` (OK/PARTIAL/FAILED/UNAVAILABLE), nunca um crash. Conceitos: isolamento de falhas, texto de erro estruturado (sem caminhos além de mountpoints).
- `src/agent/collectors/{cpu,memory,storage,system,network,hardware}.py` — leitores por domínio.
- `src/agent/platform_support/{windows,powershell,base}.py` — consultas CIM somente-leitura, `PlatformQueryError`/`PlatformUnavailableError`.

**Armazenamento e fila**
- `src/agent/storage/local_db.py` — `connect` (gravável vs `mode=ro`), migrações por `PRAGMA user_version`, marcador `PRAGMA application_id` (live vs demo), `LocalStore.save_run` (`BEGIN IMMEDIATE` atômico). Conceitos: WAL, migrações, transações, invariante run/queue.
- `src/agent/storage/queue.py` — `SyncQueue`: único escritor de `state`; claim/recover/mark_synced/mark_failed/mark_dead/release/requeue. Conceitos: máquina de estados, recuperação de lease, aplicação de backoff.

**Sync**
- `src/agent/sync/service.py` — `SyncService.run_cycle`: recuperar stale → registrar (com fingerprint) → reivindicar devidos → agrupar batches por bytes → entregar → transicionar. Conceitos: batching, re-registro em 409, motivos de aborto.
- `src/agent/sync/client.py` — Protocol de transporte + `UrllibTransport` (sem redirects) + `ApiClient` com a classificação ordenada de sete linhas. Conceitos: limite entregue vs não-entregue, mapeamento de status HTTP.
- `src/agent/sync/serializer.py` — construtor de whitelist + `scrub_ips`. Conceitos: minimização de dados, redação validada por `ipaddress`.
- `src/agent/sync/retry.py` — `BackoffPolicy.delay`: `min(max, base·2^(n-1))·uniform(0.5,1.0)`. Conceitos: backoff exponencial + jitter.

**Config / logging**
- `src/agent/config/settings.py` — `Settings`, `Thresholds`, `SyncSettings`, `Secret`, `load_settings`. `SyncSettings` fica aqui de propósito (limite de import local-first). Conceitos: precedência env > `.env` > default, validação coletando todos os erros, wrapper de secret.
- `src/agent/logging/logger.py`, `src/shared/utils/json_logging.py` — logging JSON + filtro de redação.

**Cloud**
- `src/cloud/http.py` — `Request.from_event` (API Gateway v2), `@api_handler` (aplicação de escopo + mapeamento exceção→envelope), `parse_json_body`. Conceitos: integração proxy, tabela de erros.
- `src/cloud/auth.py` — `ApiKeyProvider`: chaves de dois escopos cacheadas no SSM, parsing bearer seguro em bytes (M2). Conceitos: comparação em tempo constante, cache tolerante a valores stale.
- `src/cloud/errors.py` — hierarquia `ApiError` → status/code/headers (401 `WWW-Authenticate`, 503 `Retry-After`).
- `src/cloud/repository.py` — padrões de acesso single-table AP1–AP6b, put condicional idempotente, `to_public` removendo chaves internas, `Decimal`→`int`.
- `src/cloud/cursor.py` — cursores base64url opacos, validados estritamente e vinculados ao dispositivo.
- `src/cloud/metrics.py` — construtor de linha EMF, oito nomes de métrica, dimensão `[["Service","Function"]]`.
- `src/cloud/handlers/{health,device,telemetry,diagnostic}.py` — os quatro pontos de entrada Lambda; `_support.py` plumbing compartilhado.

**Shared**
- `src/shared/schemas/{common,device,telemetry}.py` — os validadores do contrato de API e constantes de tamanho (`MAX_REQUEST_BYTES`, `MAX_EVENT_BYTES`, `AGENT_VERSION_PATTERN`, `DEVICE_ID_PATTERN`, `MAX_CLOCK_SKEW_SECONDS`).
- `src/shared/models/{device,diagnostic}.py` — dataclasses congeladas + enums (`HealthStatus`, `NetworkStatus`, `CheckStatus`, `Severity`, `RunSource`).
- `src/shared/utils/{ids,timeutil,json_logging}.py` — UUIDv7, tempo ISO, logging JSON.

**Infra / scripts / docs**
- `infrastructure/template.yaml` + `samconfig.toml` — o backend SAM.
- `scripts/deploy.*`, `teardown.*`, `validate-infra.*`, `local_cloud.py` — auxiliares manuais de deploy/validação (nunca executados automaticamente).
- `docs/*` + `docs/decisions/ADR-00{1..7}` + `diagrams/*.mmd` — ver §4.

---

## 4. Documentation History

- `README.md` / `README.pt-BR.md` — o ponto de entrada: enunciado do problema, Mermaid de arquitetura, stack com versões, features, instalação, execução local, nota de deploy (nada implanta a partir do repo), resumos de segurança/custo/privacidade, limitações, convenção bilíngue de documentação.
- `docs/architecture.md` — componentes (tabelas Python + AWS), o diagrama de fluxo de dados, identidade, o schema SQLite, a máquina de estados de sync, a **matriz de falhas** (a página mais útil) e os desvios da especificação original. Também a nota de taxa-de-falha-de-probe-TCP explicando o que "packet loss" significa aqui.
- `docs/api.md` — o contrato `/v1` + `/health` por endpoint (ver §12).
- `docs/data-model.md` — o design DynamoDB single-table (chaves, GSI1, TTL, padrões de acesso AP1–AP6b) e as tabelas SQLite.
- `docs/security.md` — transporte, auth de dois escopos, a matriz IAM, segredos, validação de entrada, minimização de dados, retenção de `sourceIp`, limites de confiança.
- `docs/threat-model.md` — nove ameaças, cada uma com impacto/mitigação/risco residual (chave roubada, replay, MITM/redirect, vazamento em log, injeção, DoS/custo, escalonamento entre funções, exposição pela read-API, cursor adulterado).
- `docs/cost.md` — modelo de custo por serviço, drivers, a nota de cobrança de métrica custom EMF (~10–12 métricas cobráveis em meses ativos), minimização, teardown.
- `docs/observability.md` — campos de log, as oito métricas EMF e a separação, no lado do agente, entre offline e entregue-mas-falhou.
- `docs/troubleshooting.md` — primeiras verificações de operador e de deploy.
- `docs/engineering-report.md` — resumo de arquitetura/componentes/fluxo/segurança/confiabilidade/AWS/custo/testes, os números da execução final de verificação e a lista "What the developer must understand".
- `diagrams/architecture.mmd`, `data-flow.mmd`, `sync-state-machine.mmd` — fontes Mermaid embutidas nos docs e checadas por um teste de qualidade.

**ADRs** (problema · decisão · alternativas relevantes · motivo · impacto técnico):

- **ADR-001 Local-first.** Problema: um agente dependente da nuvem falha exatamente quando a rede degrada, e enviar-antes-de-persistir arrisca perda de dados. Decisão: diagnóstico/avaliação/persistência totalmente locais; sync é etapa separada e opcional lendo uma fila já persistida. Alternativas: cloud-first (perde dados em quedas), cloud-only (sem offline). Motivo: utilidade em máquinas isoladas; sem perda de dados. Impacto: exige fila local durável + máquina de estados (ADR-005); execuções com sync desabilitada não são preenchidas retroativamente (escolha deliberada de minimização).
- **ADR-002 Backend serverless.** Problema: telemetria pequena e irregular que deve custar ~nada ocioso, mantida por uma pessoa. Decisão: HTTP API Gateway + quatro Lambdas + DynamoDB + SSM + CloudWatch. Alternativas: containers/EC2 (custo sempre-ligado/patching), uma Lambda monolítica (um papel amplo demais). Motivo: custo ocioso quase-zero, menor privilégio por função. Impacto: específico de AWS; cold starts aceitáveis para um caminho assíncrono horário.
- **ADR-003 DynamoDB.** Problema: store serverless, pay-per-use, durável para poucos padrões de acesso por chave com expiração automática. Decisão: single-table (`PK=DEVICE#<id>`, GSI1 esparso, TTL), billing on-demand, idempotência por put condicional em `event_id` + hash do payload. Alternativas: RDS/Aurora (custo ocioso, mais superfície), múltiplas tabelas (leituras cruzadas). Motivo: atende aos padrões fixos de forma barata. Impacto: novos padrões de acesso podem exigir novo GSI; PITR desligado por padrão (trade-off de custo).
- **ADR-004 SQLite local.** Problema: armazenamento local durável, transacional, zero-setup. Decisão: `sqlite3` da stdlib em WAL, FKs on, migrações por `user_version`, marcador `application_id` live/demo, uma transação `BEGIN IMMEDIATE` por execução. Alternativas: arquivos planos (sem transações/locking), servidor embutido (instalar/rodar servidor na borda). Motivo: sem dependência, invariante run/queue atômico. Impacto: concorrência de escritor único; um banco travado é um exit 1 limpo.
- **ADR-005 Fila de sync offline.** Problema: resultados devem sobreviver a quedas longas e chegar à nuvem exatamente uma vez, sem busy loop. Decisão: máquina de estados explícita de `sync_queue` com auditoria por tentativa; entregue-mas-falhou faz backoff e vira dead-letter em `RETRY_LIMIT`; uma **tentativa comprovadamente não-entregue (OFFLINE) não consome o orçamento de retry**. Alternativas: contar ciclos offline contra o limite (viraria dead-letter em quedas normais), laço de retry em processo (martela a rede), broker externo (adiciona dependência). Motivo: offline é a condição normal do produto. Impacto: uma URL mal configurada que não resolve mantém eventos PENDING para sempre (visível via `status`); a recuperação de crash reclama leases `SYNCING` vencidos.
- **ADR-006 IaC com SAM.** Problema: infra reproduzível, revisável, implantável por scripts e validável offline (sem SAM CLI na máquina de dev). Decisão: AWS SAM, validado com `cfn-lint`; um papel IAM explícito por função. Alternativas: CDK (toolchain Node), Terraform (segunda linguagem + state backend), click-ops (não reproduzível). Motivo: mapeamento um-para-um com a arquitetura, CloudFormation mantém o estado. Impacto: verbosidade de IAM aceita por menor privilégio explícito; `sam validate` adiado.
- **ADR-007 Autenticação da API.** Problema: auth simples que separe escrita/leitura, mantenha segredos fora de código/logs e seja segura contra entrada hostil. Decisão: chave Bearer com dois escopos (`ingest`/`read`) em SecureStrings do SSM, cacheadas 5 min, tolerantes a stale; parsing seguro em bytes + `hmac.compare_digest`; token não-ASCII → 401 e não 500; escopo aplicado no `@api_handler`. Alternativas: Lambda authorizer/Cognito/SigV4 (mais pesados), chave única (sem separação de escopo), credenciais por dispositivo (mais gestão de chaves). Motivo: operação mínima para v1. Impacto: uma chave de ingest vazada pode forjar device IDs até rotação; `sourceIp` é a evidência de atribuição.

---

## 5. Local Agent Deep Dive

**`main.py`.** Monta a árvore do argparse (um subparser por comando, com
`--json`/`--sync`/`--force`/`--iterations` onde aplicável), define `func` no
namespace e o chama dentro de um guard de topo que mapeia `KeyboardInterrupt`
→ 130 e qualquer outra exceção → erro logado + exit 1. Nenhum comando significa
imprimir ajuda + exit 2.

**`commands.py`.** Orquestração enxuta. Cada handler carrega settings
(`_load`, retornando `None`/exit 2 em `ConfigError`), abre o banco quando
necessário, resolve identidade e executa o trabalho. Comportamentos importantes:
- Comandos somente-leitura (`hardware`, `network`, `health`, `status`, `queue list`/`stats`) nunca criam ou migram o banco e nunca importam `sync`.
- `scan` roda o pipeline, persiste, imprime o relatório; `--sync` roda um ciclo depois. A precedência de exit é **1 > 3 > 0** (`_worse_exit`): um erro de storage supera uma sync incompleta.
- Um `StorageError` durante o `scan` ainda re-roda o pipeline *sem store* para que o operador veja o estado atual, loga `event=storage_error` e sai com 1.
- `run` faz laço de scan+sync em `telemetry_interval_seconds`, dormindo de forma interrompível (fatias ≤1s) para que Ctrl+C seja responsivo; com `--iterations N` aplica a mesma precedência 1 > 3 > 0 entre as iterações.
- `queue requeue` é o único comando de manutenção que escreve na fila (dead → PENDING).

**`pipeline.py`.** `DiagnosticPipeline` contém `CollectorSet`, `Prober`,
`HealthEvaluator`, `Clock` injetados — assim demo/testes substituem por
provedores simulados sem ramificação no código de produção.
`run(device_id, store, source, *, enqueue)`:
- Garante o invariante **`device_id is None` com um `store` → `ValueError`** (uma execução sem identidade nunca pode ser persistida) usando um erro explícito, não um `assert` (`-O` o removeria).
- `_collect()` roda cada coletor via `run_collector` (isolamento).
- Roda `NetworkDiagnostics`, depois `evaluate_result` → um `DiagnosticResult`.
- Quando há `store`, `store.save_run(result, enqueue_event=enqueue)` persiste e (opcionalmente) enfileira em uma transação.

**`collectors/`.** `base.run_collector(name, fn)` é o único limite try/except:
`PartialCollection` → PARTIAL (mantém dados parciais + erros por item);
`PlatformUnavailableError` → UNAVAILABLE; `PlatformQueryError`/`OSError`/
`psutil.Error` → FAILED; qualquer outra exceção → FAILED (último recurso). Nunca
levanta; um coletor quebrado nunca aborta a execução. Strings de erro carregam
apenas a classe/mensagem do erro.

**`diagnostics/`.** `engine.collect_all` + `diagnose` + `evaluate_result`
constroem checks/alerts/metrics e os `HealthStatus`/`NetworkStatus` gerais.
`rules.py` é uma lista de funções puras `(DiagnosticInput, Thresholds) →
RuleOutcome` com nomes de check únicos e ordem fixa; uma entrada ausente gera um
check SKIPPED. `network_diagnostics.py` classifica a conectividade first-match
(UNKNOWN → OFFLINE → UNSTABLE → DEGRADED → HEALTHY) e refere-se a interfaces por
contagem. Métricas com valor `None` são omitidas (nunca null/NaN).

**`storage/local_db.py`.** `connect` é o único ponto de entrada: conexões
graváveis criam o diretório pai, habilitam WAL + foreign keys e migram por
`PRAGMA user_version`; conexões somente-leitura abrem `mode=ro`, nunca migram e
levantam `SchemaOutdatedError` em versão antiga. `LocalStore.save_run` escreve a
execução, seus resultados e (opcionalmente) o evento de fila em uma transação
`BEGIN IMMEDIATE`, congelando o JSON do payload para que retries enviem bytes
idênticos.

**`storage/queue.py`.** `SyncQueue` é dona de toda escrita de `state` (ver §6).

**`sync/`.** `service.SyncService.run_cycle` orquestra um ciclo;
`client.ApiClient` classifica desfechos HTTP; `serializer` minimiza/higieniza;
`retry.BackoffPolicy` calcula atrasos com jitter (ver §6 e §7).

**`demo.py`.** `diagnostic-agent demo` roda o pipeline/regras/serializer/
relatório *reais* sobre provedores simulados de coletor + probe, tornando a saída
determinística e sem tocar na rede real, no banco live, no PowerShell nem no
psutil (um teste faz `subprocess`, `socket` e `psutil` levantarem exceção). Seis
cenários: HEALTHY, DEGRADED_NETWORK, LOW_DISK, HIGH_MEMORY, DNS_FAILURE,
OFFLINE_MODE. O `OFFLINE_MODE` roda ainda um ciclo de sync contra um endpoint
inalcançável `demo.invalid`, de modo que a fila fica PENDING com uma tentativa
OFFLINE por evento, com o orçamento intacto. Ver §8 para o guard de exclusão.

### O pipeline principal: collect → diagnose → persist → enqueue

Baseado em `pipeline.py` + `local_db.py`:

1. **collect.** `_collect()` monta um `Collected` rodando cada coletor via
   `run_collector`. Erros são capturados como status; a execução sempre prossegue.
2. **diagnose.** `NetworkDiagnostics(prober, settings).run(collected.network)`
   sonda gateway/internet/DNS e classifica; `evaluate_result` roda as regras de
   saúde em checks/alerts/metrics e deriva o status geral. Falhas de probe/regra
   degradam para SKIPPED/UNKNOWN, não crashes.
3. **persist.** Se há `store`, `save_run` insere uma linha `diagnostic_runs` + as
   linhas achatadas `diagnostic_results` em uma transação. Um `sqlite3.Error` vira
   `StorageError` (com rollback; o chamador sai com 1 mas ainda imprime o relatório).
4. **enqueue.** Dentro da *mesma* transação, quando
   `enqueue=settings.sync_enabled` é verdadeiro, uma linha `sync_queue` é inserida
   (estado PENDING, `attempt_count=0`, `payload_json` congelado). Isso garante o
   invariante: uma execução persistida que deve sincronizar sempre tem um evento
   de fila, e todo evento enfileirado tem sua execução.

Resumo do tratamento de erros: erros de coletor → status da seção, execução
continua; entrada de regra ausente → SKIPPED; erro de storage → `StorageError`,
rollback, exit 1, relatório ainda impresso; o próprio pipeline nunca faz I/O de
rede.

---

## 6. SQLite and Offline Queue

**Tabelas** (`_SCHEMA_V1` em `storage/local_db.py`):
- `devices(device_id PK, device_name, hostname, is_local CHECK(0,1), created_at, registration_fingerprint, registered_at)` com um **índice único parcial** `idx_devices_single_local ON devices(is_local) WHERE is_local = 1` (no máximo uma identidade local).
- `diagnostic_runs(run_id PK, device_id FK, source CHECK('live','demo'), scenario, started_at, finished_at, status, network_status, result_json)`; índice `(device_id, started_at DESC)`.
- `diagnostic_results(id PK AUTOINCREMENT, run_id FK ON DELETE CASCADE, result_type CHECK('check','alert','metric'), name, status, value, unit, subject, details_json)`.
- `sync_queue(event_id PK, run_id UNIQUE FK, device_id FK, event_type DEFAULT 'diagnostic_run', payload_json, state CHECK(PENDING,SYNCING,SYNCED,FAILED,DEAD_LETTER), attempt_count, next_attempt_at, claimed_at, last_error, created_at, updated_at, synced_at)`; índice `(device_id, state, next_attempt_at)`.
- `sync_attempts(id PK AUTOINCREMENT, event_id FK, attempted_at, outcome CHECK(ACCEPTED,DUPLICATE,REJECTED,TRANSIENT_ERROR,OFFLINE,AUTH_ERROR,CONFIG_ERROR,INTERRUPTED), http_status, error_code, error_message, duration_ms, request_id)`; índice em `event_id`.

**Migrações.** Chaveadas por `PRAGMA user_version` (atualmente
`SCHEMA_VERSION = 1`). Em um banco gravável versão-0, `_migrate` roda o script do
schema, define `PRAGMA application_id` como `DEMO_DB_APPLICATION_ID` (demo) ou
`LIVE_DB_APPLICATION_ID` (live), e então `user_version = 1`.

**WAL.** `PRAGMA journal_mode = WAL` mais `busy_timeout = 5000ms` em conexões
graváveis, para que leitores não bloqueiem o único escritor e locks transitórios
aguardem.

**Transações.** `LocalStore._transaction` envolve o trabalho em `BEGIN IMMEDIATE`
com rollback em qualquer `BaseException`. As reivindicações da fila (`claim_due`)
também usam `BEGIN IMMEDIATE` para que só linhas realmente atualizadas para
SYNCING sejam retornadas (sem envio duplicado).

**Estados e transições da fila** (`storage/queue.py`): `PENDING → SYNCING →
(SYNCED | FAILED | DEAD_LETTER)`. `FAILED` fica devido de novo quando
`next_attempt_at <= now`. `release` devolve uma linha reivindicada para PENDING
(se `attempt_count == 0`) ou FAILED (caso contrário) **sem contar uma tentativa**.
`requeue_dead` move DEAD_LETTER → PENDING com `attempt_count = 0`.

**Retry / backoff / jitter.** `BackoffPolicy.delay(attempt)` =
`min(max_s, base_s · 2^(attempt-1)) · uniform(0.5, 1.0)` com um RNG injetado
(determinístico em testes). **Não há laço de retry em processo**: um evento FAILED
apenas aguarda um ciclo posterior. `mark_failed` vira dead-letter em
`attempt >= retry_limit`, senão define FAILED com um `next_attempt_at` de backoff.

**Recuperação de stale.** `recover_stale` encontra linhas presas em SYNCING com
`claimed_at` mais antigo que `SYNC_LEASE_SECONDS = 300`, registra uma tentativa
`INTERRUPTED` (contada, porque a requisição pode ter sido entregue) e as move
para FAILED com `attempt_count + 1`.

**Dead-letter.** Alcançado por rejeição permanente (`mark_dead`) ou por esgotar
`retry_limit` (`mark_failed`). Recuperável só via `queue requeue`.

**Idempotência / event_id.** `event_id` é um UUIDv7 (ordenado no tempo) gerado no
enqueue; `run_id` é UNIQUE para que uma execução mapeie para exatamente um evento;
o `payload_json` congelado significa que todo retry envia conteúdo byte-idêntico,
que a nuvem trata como o mesmo item (ver §11).

**Máquina de estados (textual), de acordo com `queue.py`:**

```
            enqueue durante o scan
                 │
                 ▼
             [PENDING] ──claim_due──► [SYNCING] ──accepted/duplicate──► [SYNCED] ─► fim
                 ▲                        │
   release(attempt_count==0)              ├── erro transiente, attempt<limit ─► [FAILED]
                 │                        │                                      │
                 │                        ├── rejected OU attempt>=limit ─► [DEAD_LETTER]
                 │                        │                                      │
                 │                        └── release(offline/auth/config):      │
                 │             attempt_count==0 → PENDING, senão → FAILED         │
                 │                                                                │
             [FAILED] ──claim_due (next_attempt_at<=now)──► [SYNCING]             │
                                                                                  │
             [DEAD_LETTER] ──queue requeue──► [PENDING] ◄────────────────────────┘

   Lease vencido: [SYNCING] (claimed_at mais antigo que SYNC_LEASE_SECONDS)
                → tentativa INTERRUPTED (contada) → [FAILED]
   Nota: tentativas OFFLINE são registradas em sync_attempts mas nunca consomem RETRY_LIMIT.
```

---

## 7. Synchronization Flow

Como um evento sai do SQLite e chega ao backend (`sync/service.py`,
`sync/client.py`, `storage/queue.py`):

1. **Guardar & recuperar.** `run_cycle` retorna `disabled` quando a sync está
   desligada/sem chave. Registra `other_device_pending`, roda `recover_stale` e
   retorna cedo se nada estiver devido.
2. **Registrar (com fingerprint).** `_ensure_registration` monta o payload de
   registro a partir dos fatos da execução mais recente, faz hash (SHA-256) e pula
   a chamada se inalterado. Falhas de registro passam por `_handle_registration_failure`.
3. **Reivindicar.** `claim_due` move atomicamente até `batch_size` linhas devidas
   para SYNCING (ordenadas por `next_attempt_at`, depois `created_at`), excluindo
   eventos já tratados no ciclo.
4. **Agrupar por bytes.** `_pack` adiciona eventos gulosamente enquanto o envelope
   serializado permanece `<= MAX_REQUEST_BYTES` (256 KiB) e `len <= batch_size`; o
   excedente é liberado (sem contar) para um batch posterior. Até `max_batches`
   batches por ciclo.
5. **Entregar & classificar.** `ApiClient.send_telemetry` roda a classificação
   ordenada de sete linhas; a máquina de estados da fila aplica o resultado.

**Classificação HTTP** (`client.py`, primeira correspondência vence):
- **Linha 1 — não entregue / entrega incerta.** `ConnectivityError` →
  `OfflineError`; `DeliveryUncertainError` (timeout, reset após envio, TLS, outro
  OSError depois que a requisição saiu) → `TransientSyncError`.
- **Linha 2 — redirect (3xx).** Recusado por `_NoRedirect` → `ConfigurationError`
  (a chave de ingest nunca é copiada para outro host).
- **Linha 3 — 401/403.** `AuthError`.
- **Linha 4 — 429 / 500 / 502 / 503 / 504.** `TransientSyncError` (carrega status).
- **Linha 5 — corpo 2xx malformado.** `MalformedResponseError` (subclasse de
  `TransientSyncError`; retry é seguro).
- **Linha 6 — 4xx com envelope.** 409 `DEVICE_NOT_REGISTERED` →
  `DeviceNotRegisteredError`; 413 multi-evento → `PayloadTooLargeError`; 413 evento
  único → `PermanentSyncError`; outro 4xx com envelope → `PermanentSyncError`.
- **Linha 7 — qualquer outra coisa.** `ConfigurationError`.

**Resposta do serviço a cada desfecho** (`service.py`):
- **offline** → libera o batch (tentativa OFFLINE), aborta o ciclo, `aborted="offline"`.
- **401/403** → libera (AUTH_ERROR), `aborted="auth"`.
- **config/redirect/inesperado** → libera (CONFIG_ERROR), `aborted="config"`.
- **413 (multi)** → `_split_413`: libera, reenvia um evento por requisição.
- **permanente (4xx com envelope / 413 único)** → `_dead` cada evento → DEAD_LETTER.
- **409** → `_handle_409`: re-registra uma vez e re-entrega; se o próprio re-registro falhar, roteia pelas suas próprias ramificações.
- **malformed / transiente (incl. 5xx/429/entrega-incerta)** → `_fail` cada evento (conta uma tentativa; FAILED com backoff ou DEAD_LETTER no limite).
- **200 bem-formado** → `_apply_items`: `accepted`/`duplicate` → `mark_synced`; `CLOCK_SKEW` → `_fail` (transiente, logado); qualquer outro código por item → `_dead`.

**Re-registro.** Em 409 o serviço registra de novo (se `allow_reregister`),
armazena o novo fingerprint e re-entrega o mesmo batch; a entrega interna desliga
novos re-registros para evitar laços.

**A regra do orçamento de retry — verificada contra o código.** Uma **tentativa
comprovadamente não-entregue (offline) não consome o orçamento de retry**:
`ConnectivityError → OfflineError` leva a `SyncQueue.release`, que não incrementa
`attempt_count` e deixa `next_attempt_at` inalterado. A mesma liberação sem
contagem vale para abortos 401/403 e config/redirect. Isso bate com a ADR-005,
com `docs/observability.md` e com a matriz de falhas, e é comprovado por
`tests/integration/test_offline.py` (após um scan+sync offline o evento continua
PENDING, `attempt_count == 0`, `next_attempt_at` inalterado, com uma linha de
tentativa `OFFLINE`).

**Nuance importante (não é divergência, mas é facilmente mal interpretada).**
"Falha de rede" é dividida em duas. Só o caso *comprovadamente não entregue* é
OFFLINE e não contabilizado. Uma falha de **entrega incerta** (conexão
estabelecida e então timeout/reset, erro TLS, ou qualquer OSError levantado após
a requisição ser enviada) é classificada como `DeliveryUncertainError →
TransientSyncError` e **consome** o orçamento (pode ter sido entregue, então deve
fazer backoff e pode virar dead-letter). Assim, a regra precisa é:
*abortos offline/não-entregue e auth/config não consomem o orçamento; falhas
entregues-ou-talvez-entregues consomem.* `docs/observability.md`
("Agent-side sync-failure split") afirma exatamente isso.

---

## 8. Security Review

Controles principais: HTTPS com verificação de certificado e **sem redirects**;
auth Bearer de dois escopos com chaves no SSM; um papel IAM de menor privilégio
por função (sem wildcards); validação estrita por schema compartilhado nos dois
lados; minimização de dados + higienização de IP antes do upload; wrapper
`Secret` + redação de log.

### (a) `demo.py` — recusar apagar um arquivo SQLite arbitrário (M1)

`DEMO_DATABASE_PATH` é configurável pelo usuário, então um ingênuo "apagar
demo.db no início de cada execução" poderia destruir um arquivo que o agente não
criou. O guard (`DemoRunner.prepare_database`):
1. Recusa (exit 2) quando `DEMO_DATABASE_PATH` resolve para o mesmo arquivo de `DATABASE_PATH`.
2. Se o arquivo demo existe, abre-o somente-leitura e checa `PRAGMA application_id`.
   Só apaga o arquivo e seus irmãos `-wal`/`-shm` **quando** o id for igual a
   `DEMO_DB_APPLICATION_ID` (o marcador fixo escrito na criação do banco demo).
   Um arquivo SQLite estrangeiro (ex.: um banco live copiado, que carrega
   `LIVE_DB_APPLICATION_ID`) ou um arquivo não-SQLite é deixado intacto e o
   comando sai com 2.

Risco reduzido: exclusão destrutiva acidental de um banco não relacionado por
erro de digitação/configuração. Verificado por `tests/unit/agent/test_demo.py`
(`test_demo_leaves_foreign_sqlite_file_untouched`,
`test_demo_leaves_non_sqlite_file_untouched`, `test_demo_refuses_same_file_as_live_db`).

### (b) `auth.py` — auth Bearer; token não-ASCII deve ser 401 e não 500 (M2)

`_extract_bearer` parseia o header `Authorization` não confiável de forma
defensiva: `None` para headers ausentes / grandes demais (`> MAX_AUTH_HEADER_CHARS
= 512`) / não-`Bearer` (esquema insensível a maiúsculas) / com token vazio; caso
contrário codifica o token em **bytes** com `surrogatepass`. `_matches` compara
bytes com `hmac.compare_digest`. Isso importa porque `hmac.compare_digest`
levanta `TypeError` em argumentos `str` não-ASCII — então comparar um token
`Bearer é…` cru como string surgiria como uma exceção genérica → **500
`INTERNAL_ERROR`** com traceback e uma métrica `LambdaError` inflada. Ao retornar
`None`/bytes vira um **401** limpo. Ambas as comparações de escopo sempre rodam
(trabalho constante, então o tempo nunca revela qual chave esteve mais perto);
token inválido → `Unauthorized` (401), chave válida com escopo errado →
`Forbidden` (403). Verificado por `tests/unit/cloud/test_auth.py` (não-ASCII,
grande demais, `Basic`, `bearer` minúsculo, token vazio todos → 401).

### (c) `serializer.py` — whitelist, higienizador de IP, tratamento de interfaces (M3)

`build_event` é uma **whitelist explícita**: só `event_id`, `event_type`,
`schema_version`, `timestamp`, `source`, `status`, `network_status` e os
`checks`/`alerts`/`metrics` higienizados são enviados. `scrub_ips` substitui um
token por `<ip>` **apenas quando `ipaddress` o aceita**, então literais IPv4/IPv6
(incl. `fe80::1%12`, `2001:db8::53`) são redigidos enquanto `16:42:03`, `C:\` e
`87.0%` sobrevivem. Nomes de interface são tratados estruturalmente: as regras de
rede referem-se a interfaces **apenas por contagem** (`network_diagnostics.py`),
então os nomes ficam nos `facts` locais e nunca chegam à evidência enviada; o
higienizador é defesa em profundidade para qualquer IP que ainda caia em uma
string.

**O que NÃO é enviado:** nomes de interface, servidores DNS, IPs de gateway,
qualquer literal de IP, strings de modelo de disco físico e GPU (discos são
referenciados por posição `disk{index}`) e — conforme `docs/security.md` —
histórico de navegação, documentos, teclas digitadas, screenshots, endereços MAC,
números de série, nomes de usuário. Verificado por
`tests/unit/agent/test_serializer.py` (o sentinela
`SENTINEL-IFACE`/`fe80::1%12`/`2001:db8::53`/IPv4 não vaza nada; `C:`/`87.0%`
sobrevivem). Isso é minimização de dados / privacy-by-design: minimizar na
origem, aplicar via whitelist + regras estruturais e higienizar como rede de
segurança.

### Outros controles

- **Identidade UUID do dispositivo.** Um UUIDv4 aleatório na primeira execução,
  armazenado `is_local=1`; um override `DEVICE_ID` é armazenado `is_local=0`; o
  hostname é um atributo, nunca a chave — então a identidade é independente de IP
  e de seriais de hardware (`identity.py`).
- **Event IDs / idempotência.** `event_id` UUIDv7 + um payload congelado tornam o
  put condicional da nuvem exatamente-uma-vez (mesmo payload = duplicata, payload
  diferente = `EVENT_ID_CONFLICT`); ver §11.
- **Segredos.** `Secret` envolve chaves para que `repr`/`str` sejam `***`; um
  filtro de redação de log descarta extras que casem com
  `key|token|secret|password|authorization`; um teste de vazamento de segredo
  afirma que uma chave-sentinela não aparece em nenhum log. Chaves da nuvem ficam
  em SecureStrings do SSM e nunca são logadas.
- **Menor privilégio.** Um papel IAM por Lambda, sem managed policies, sem ações
  wildcard, recursos de log/DynamoDB/SSM escopados (ver §10).
- **Sem operações remotas invasivas.** Não há execução remota de comandos, nem
  escrita de volta ao host a partir da nuvem; coletores/consultas de plataforma
  são somente-leitura; o agente apenas faz POST de telemetria minimizada.

---

## 9. AWS Architecture Deep Dive

Toda a configuração abaixo é lida de `infrastructure/template.yaml`.

- **HTTP API Gateway** (`AWS::Serverless::HttpApi`, payload format 2.0). Problema:
  uma entrada pública HTTPS que roteia/throttle de forma barata. Config aqui:
  `StageName=!Ref Stage`, throttling em `DefaultRouteSettings`
  (`ThrottleRateLimit`/`ThrottleBurstLimit`), `AccessLogSettings` JSON para um log
  group dedicado (captura `sourceIp`, `routeKey`, `status`, latência). Conecta-se
  ao agente via `Authorization: Bearer`; roteia para as quatro funções. Conceitos
  de certificação: HTTP API vs REST API, stages, throttling, access logging.
- **Lambda ×4** (`health`, `device`, `telemetry`, `diagnostic`). Problema:
  computação stateless por rota sem servidores. Config aqui: `python3.13`,
  `arm64`, `MemorySize=128`, `Timeout=10`, `CodeUri: ../src` compartilhado, env
  vars (`TABLE_NAME`, `INGEST_KEY_PARAMETER`, `READ_KEY_PARAMETER` e
  `DIAGNOSTIC_RETENTION_DAYS` para telemetry), cada uma ligada aos eventos do HTTP
  API da(s) sua(s) rota(s), cada uma com seu `Role`. Conceitos: computação
  orientada a eventos, cold starts, integração proxy, config por função,
  custo de memória/arquitetura.
- **DynamoDB** (`AWS::DynamoDB::Table`). Problema: store chave-valor durável,
  idempotente e pay-per-use. Config aqui: `BillingMode=PAY_PER_REQUEST`, chaves
  `PK` (HASH) / `SK` (RANGE), `GSI1` (`GSI1PK`/`GSI1SK`, `ProjectionType: ALL`),
  `TimeToLiveSpecification` em `expires_at`. Conceitos: single-table design,
  partition/sort keys, GSIs, on-demand vs provisionado, TTL, escritas condicionais.
- **CloudWatch**. Problema: observabilidade sem chamadas de API extras. Config
  aqui: um `AWS::Logs::LogGroup` por função + um log group de acesso da API, todos
  com `RetentionInDays=!Ref LogRetentionDays` (padrão 14) e
  `DeletionPolicy: Delete`. Métricas via EMF (`src/cloud/metrics.py`): namespace
  `DiagnosticGateway`, dimensão `[["Service","Function"]]`, 8 nomes de métrica.
  Conceitos: Logs vs Metrics, EMF, retenção, cobrança de métrica custom.
- **SSM Parameter Store**. Problema: guardar as duas chaves de API de forma
  barata. Config aqui: os *nomes* dos parâmetros são parâmetros do template
  (`IngestKeyParameterName`, `ReadKeyParameterName`); os valores SecureString são
  provisionados **fora da stack**. Carregados por
  `GetParameters(WithDecryption=True)`. Conceitos: SecureString vs Secrets
  Manager, decrypt KMS `alias/aws/ssm`, ARNs de parâmetro.
- **IAM**. Problema: menor privilégio por função. Config aqui: um
  `AWS::IAM::Role` explícito por função, sem managed policies, sem ações wildcard
  (ver §10). Conceitos: trust policy de assume-role, políticas inline, ARNs de
  recurso escopados.
- **SAM**. Problema: declarar todo o backend como código revisável. Config aqui:
  `Transform: AWS::Serverless-2016-10-31`, `Globals.Function`, parâmetros,
  `Outputs` (`ApiBaseUrl`, `TableName`, `IngestKeyParameterName`). Validado offline
  com `cfn-lint`; nunca implantado do repo. Conceitos: IaC, transform/intrínsecos
  do CloudFormation, drift/estado no CloudFormation.

---

## 10. IAM Review

Conforme `infrastructure/template.yaml`. Todo papel tem uma trust policy de
assume-role de `lambda.amazonaws.com` e apenas políticas inline. ARNs de recurso
são construídos a partir de `${AWS::Partition}/${Region}/${AccountId}` para que
nada seja wildcard.

| Função | Papel | Permissões | Recursos permitidos | Motivo |
|---|---|---|---|---|
| health | `HealthRole` | `logs:CreateLogStream`, `logs:PutLogEvents` | seu próprio log group `/aws/lambda/${StackName}-health:*` | Apenas liveness; não toca em nenhum serviço de apoio, logo sem DynamoDB/SSM. |
| device | `DeviceRole` | logs (grupo próprio) + `dynamodb:UpdateItem`,`GetItem`,`Query` + `ssm:GetParameters` | ARN da tabela **e** `.../index/GSI1`; os dois ARNs de parâmetro de chave | Precisa de upsert (AP1), ler um (AP2), listar via GSI1 (AP3); auth precisa das duas chaves. Sem `PutItem`/`DeleteItem`. |
| telemetry | `TelemetryRole` | logs (grupo próprio) + `dynamodb:GetItem`,`PutItem`,`UpdateItem` + `ssm:GetParameters` | só o ARN da tabela (sem índice); os dois ARNs de parâmetro | Precisa checar existência do dispositivo (GetItem), ingestão condicional (PutItem AP4), latest/last-seen (UpdateItem AP6/AP6b). Sem `Query`/`DeleteItem`; sem acesso ao GSI. |
| diagnostic | `DiagnosticRole` | logs (grupo próprio) + `dynamodb:GetItem`,`Query` + `ssm:GetParameters` | só o ARN da tabela; os dois ARNs de parâmetro | Precisa de existência do dispositivo (GetItem) e listagem newest-first (Query AP5). Somente-leitura nos dados; sem escritas, sem GSI. |

Notas de menor privilégio: nenhum papel concede `dynamodb:DeleteItem` ou `Scan`;
permissões de log são escopadas ao ARN do grupo próprio de cada função; o SSM é
limitado aos dois ARNs de parâmetro; o decrypt KMS das SecureStrings usa a chave
gerenciada `alias/aws/ssm` (dependência de deploy, não um statement explícito
aqui). As permissões foram lidas do template, não inferidas.

---

## 11. DynamoDB Review

De `src/cloud/repository.py` e `docs/data-model.md`.

**Single-table design.** Uma tabela guarda dois tipos de entidade compartilhando
uma partição por dispositivo:
- **Partition key `PK`** = `DEVICE#<device_id>` para ambas as entidades.
- **Sort key `SK`** = `PROFILE` para o perfil do dispositivo; `DIAG#<event_id>`
  para um evento. Como `event_id` é um UUIDv7 ordenado no tempo, `DIAG#…` ordena
  cronologicamente, logo "mais novo primeiro" é um `Query` reverso
  (`ScanIndexForward=False`).
- **GSI1** (`GSI1PK=DEVICE`, `GSI1SK=DEVICE#<id>`) é **esparso**: só perfis o
  carregam, então "listar dispositivos" varre apenas perfis.
- **`entity`** = `"device"` / `"diagnostic"`.

**Padrões de acesso.** AP1 registrar/atualizar (`update_item` upsert,
idempotente); AP2 obter um perfil; AP3 listar dispositivos (Query GSI1,
paginado); AP4 ingestão (`put_item` condicional); AP5 diagnósticos recentes
(Query `begins_with(SK,'DIAG#')` reverso); AP6 atualizar o latest status
(`update_item` guardado); AP6b avançar `last_seen_at`.

**Escritas condicionais / idempotência.** `DiagnosticRepository.put_event` usa
`ConditionExpression="attribute_not_exists(PK)"` com
`ReturnValuesOnConditionCheckFailure="ALL_OLD"`. Em um conflito compara o
`payload_sha256` armazenado com o novo: igual → `DUPLICATE` (um item armazenado);
diferente → `CONFLICT` → o handler retorna por item `EVENT_ID_CONFLICT`. O
`update_latest` do AP6 é guardado por
`attribute_exists(PK) AND (attribute_not_exists(latest_event_id) OR latest_event_id < :eid)`
para que um evento mais antigo não sobrescreva um mais novo; uma condição que
falha cai para `touch_last_seen`.

**TTL.** Eventos carregam `expires_at` (segundos epoch = `received_at +
retention_days·86400`, padrão 30) e o `TimeToLiveSpecification` da tabela em
`expires_at` os expira de graça. Perfis não têm TTL.

**Modelagem pública.** `to_public` / `diagnostic_to_public` nunca retornam
`PK`/`SK`/`GSI1*`/`entity`/`payload_sha256`/`payload`, e convertem `Decimal` do
DynamoDB de volta para `int` (`_decimals_to_int`). Exemplo de item diagnóstico
armazenado (`build_diagnostic_item`): `PK=DEVICE#id`, `SK=DIAG#<event_id>`,
`entity=diagnostic`, `status`/`network_status`/`alert_count`/`timestamp` nativos,
um `payload` em JSON compacto com `checks`/`alerts`/`metrics`, mais
`payload_sha256` e `expires_at`.

---

## 12. API Contract

De `src/cloud/handlers/*` e `docs/api.md`. Todas as respostas são
`application/json`. Envelope de erro: `{ "error": { code, message, request_id,
details? } }`. Limites de tamanho (`shared/schemas/common.py`): registro ≤ 8 KiB,
telemetria ≤ 256 KiB, ≤ 10 eventos/requisição, cada evento ≤ 32 KiB. Janela de
clock-skew = 300 s.

- **GET `/health`** — auth: nenhuma (`scope=None`). Sem corpo. 200 → `{status,
  service, version, time}`. Sem chamadas AWS; papel só com logs.
- **POST `/v1/devices`** — auth: `ingest`. Corpo = registro (`schema_version`,
  `device_id`, `device_name`, `os{name,version,architecture}`,
  `hardware{cpu_model?,logical_cpus,physical_cores?,memory_total_bytes}`,
  `agent_version`), validado por `validate_device_registration`. 201 criado /
  200 atualizado → `{device_id, created, registered_at, updated_at}` (upsert
  idempotente AP1). Erros: 400 `VALIDATION_ERROR`, 401, 403, 413.
- **GET `/v1/devices`** — auth: `read`. Query `limit` (1–100, padrão 25),
  `cursor`. 200 → `{items:[public device], next_cursor}`. Erros: 400
  `INVALID_CURSOR`, 401, 403.
- **GET `/v1/devices/{device_id}`** — auth: `read`. `device_id` deve casar com
  `DEVICE_ID_PATTERN`, senão 400. 200 → device público (`device_id, device_name,
  os, hardware, agent_version, registered_at, updated_at, last_seen_at, latest`);
  chaves internas removidas. Erros: 400, 401, 403, 404 `NOT_FOUND`.
- **POST `/v1/telemetry`** — auth: `ingest`. Corpo = `{schema_version, device_id,
  events:[…1–10…]}`. Ordem: checar tamanho → parsear JSON → validar envelope →
  GetItem do dispositivo (ausente → 409 `DEVICE_NOT_REGISTERED`) → `validate_event`
  por evento → put condicional → AP6/AP6b → resposta por item. 200 → `{device_id,
  accepted, duplicates, rejected, results:[{event_id, status, error?}]}`. Códigos
  por item: `EVENT_ID_CONFLICT`, `CLOCK_SKEW`, `VALIDATION_ERROR`. Erros: 400
  `INVALID_JSON`/`VALIDATION_ERROR`, 401, 403, 409, 413, 503
  `SERVICE_UNAVAILABLE` (DynamoDB transiente no meio do batch).
- **GET `/v1/devices/{device_id}/diagnostics`** — auth: `read`. Query `limit`
  (1–50, padrão 20), `cursor` (vinculado ao `device_id`). Dispositivo ausente →
  404. 200 → `{device_id, items:[{event_id, timestamp, received_at, source,
  status, network_status, alert_count, checks, alerts, metrics}], next_cursor}`.
  Erros: 400 (id inválido / `INVALID_CURSOR`), 401, 403, 404.

**Validação & tratamento de erro.** O schema compartilhado é o único contrato (o
agente pré-valida do mesmo jeito). `@api_handler` mapeia exceções para a tabela
B.14: `ApiError` → seu status/code/headers (401 adiciona
`WWW-Authenticate: Bearer`, 503 adiciona `Retry-After: 5`); `ClientError`
transiente → 503 `SERVICE_UNAVAILABLE`; qualquer outra coisa → 500 genérico
`INTERNAL_ERROR` (sem traceback ao cliente). Os `details` de validação carregam
apenas nomes de campo + problemas, nunca valores, e são limitados a 20.

---

## 13. Testing Strategy

A suíte foi executada no `.venv` do projeto: **357 passed** (confirmado por
`python -m pytest -q`; o `docs/engineering-report.md` cita o mesmo número, com
ruff/mypy/cfn-lint também limpos). O ponto não é a contagem, mas *o que os testes
provam*. Layout: `tests/unit/{agent,cloud,shared}`, `tests/integration`,
`tests/infra`, `tests/quality`, `tests/support`, `tests/fixtures`.

**Tipos de teste.**
- **unit** — isolam um módulo com fakes injetados (relógios, probers, stubs de SSM/transporte).
- **integration** — ponta a ponta contra caminhos reais: `test_sync_e2e.py` roda o `ApiClient` do agente contra os handlers Lambda *reais* sobre um servidor HTTP local; `test_offline.py` roda comandos CLI reais com as primitivas de rede patcheadas para falhar.
- **moto** — `test_handlers_moto.py` invoca os handlers reais com eventos API Gateway v2 contra DynamoDB/SSM de `moto.mock_aws` (sem conta AWS).
- **offline** — simulam ausência de conectividade e verificam comportamento local-first + estado da fila.
- **failure paths** — ramos de erro: falha de storage, 5xx transiente, split de 413, re-registro em 409, clock skew, entrega incerta.
- **contract/validation** — `shared/test_validation.py`, `agent/test_contract.py`: a saída do agente sempre passa no validador da nuvem; `bool`-como-número e campos desconhecidos rejeitados; `AGENT_VERSION_PATTERN` vale.
- **quality gates** — `test_import_boundaries.py` (varredura AST: `shared` só stdlib, `cloud` sem `agent`, `agent` sem `cloud`, `agent.config` sem `agent.sync`), `test_secret_leak.py`, `test_diagrams_in_sync.py`, `test_adr_structure.py`.

**Agrupados pelo que provam.**
- *Comportamento funcional:* desfechos de cenário (`test_demo.py` mapeia os seis cenários para status/alerts exatos); classificação (`test_network_classification.py`); exit codes da CLI (`test_cli_exit_codes.py`); round-trips de schema/serializer; padrões de acesso do repository sob moto.
- *Segurança:* `test_auth.py` (não-ASCII/grande demais/`Basic`/lowercase-bearer/vazio → 401; chave-válida-escopo-errado → 403; tolerância a chave stale; dependência indisponível); `test_serializer.py` sentinela M3 (sem vazamento de nome de interface/DNS/gateway/IP; strings seguras sobrevivem); `test_demo.py` guards M1 (arquivos estrangeiro/não-SQLite intactos, recusa de mesmo arquivo); `test_secret_leak.py`; `test_public_device.py` (sem vazamento de chaves internas); `test_cursor.py` (cursor adulterado → `INVALID_CURSOR`).
- *Integração:* `test_sync_e2e.py` (client ↔ handlers reais), `test_handlers_moto.py` (handlers ↔ DynamoDB/SSM moto), `test_template.py` (asserções sobre o template SAM via decode do cfn-lint).
- *Regressão:* os testes M1/M2/M3 existem especificamente para fixar as três correções MEDIUM; o teste de limite de import fixa a garantia local-first; `test_run_loop.py` fixa a precedência de exit do `--iterations`.
- *Casos de borda:* fixtures de parsing de ping (`tests/fixtures/ping/*`, en + pt-BR, timeout, inalcançável), enums PowerShell numéricos-vs-string (`tests/fixtures/powershell/*`), limite de clock-skew (299 s aceito), omissão de métrica `None`, entrega incerta vs offline.

---

## 14. Configuration and Environment

**Agente** (`src/agent/config/settings.py`, documentado em `.env.example`).
Precedência: env de processo > arquivo `.env` > default embutido. Exatamente um
`.env` é carregado: `--env-file` > `./.env` > `<data dir>/.env`. Valores inválidos
levantam `ConfigError` listando todas as chaves ruins. Segredos são embrulhados em
`Secret`.

| Variável | Padrão | Limites | Consumida em |
|---|---|---|---|
| `API_BASE_URL` | "" (sync desligada) | https:// (http só para localhost) | `_validate_api_base_url`, `sync_enabled`, ApiClient |
| `AGENT_API_KEY` | "" | 32–256 chars; obrigatória quando a URL é setada | header de auth do ApiClient |
| `DEVICE_ID` | "" (gerar) | `^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$` | `identity.resolve_device_id` |
| `DEVICE_NAME` | "" (hostname) | 1–64 chars | identity, registro |
| `TELEMETRY_INTERVAL_SECONDS` | 3600 | 300–86400 | laço `cmd_run` |
| `DATABASE_PATH` | `<data dir>/agent.db` | caminho | `local_db.connect` |
| `DEMO_DATABASE_PATH` | `<data dir>/demo.db` | caminho | `DemoRunner` |
| `LOG_LEVEL` | INFO | DEBUG/INFO/WARNING/ERROR | setup de logging |
| `LOG_FILE` | `<data dir>/logs/agent.log` | caminho | logger |
| `RETRY_LIMIT` | 5 | 1–20 | `SyncSettings.retry_limit` → queue |
| `RETRY_BACKOFF_BASE_SECONDS` | 60 | 1–3600 | `BackoffPolicy.base_s` |
| `RETRY_BACKOFF_MAX_SECONDS` | 3600 | ≥ base, ≤ 86400 | `BackoffPolicy.max_s` |
| `SYNC_BATCH_SIZE` | 10 | 1–10 | `_pack`, `claim_due` |
| `SYNC_MAX_BATCHES_PER_CYCLE` | 5 | 1–100 | limite do laço de `run_cycle` |
| `HTTP_TIMEOUT_SECONDS` | 10.0 | 1–60 | timeout do ApiClient |
| `CPU_SAMPLE_COUNT` | 3 | 1–10 | `collect_cpu` |
| `CPU_SAMPLE_INTERVAL_SECONDS` | 1.0 | 0.1–5 | `collect_cpu` |
| `CPU/MEMORY/DISK_*_PERCENT`, `LATENCY_WARNING_MS`, `PACKET_LOSS_*_PERCENT` | 90/90/85/95/150/10/30 | faixas; crit>warn, unstable>warn | `Thresholds` → rules/classificação |
| `NETWORK_PROBE_COUNT` | 4 | 1–10 | probes |
| `NETWORK_PROBE_TIMEOUT_SECONDS` | 2.0 | 0.5–10 | probes |
| `INTERNET_TARGETS` | `1.1.1.1:443,8.8.8.8:443` | 1–5 `host:port` (IPv6 entre colchetes) | probes de internet |
| `DNS_TEST_HOSTNAMES` | `example.com,aws.amazon.com` | 1–5 RFC-1123 | probes de DNS |

**Nuvem** (`src/cloud/config.py`): cada handler declara seu `REQUIRED_ENV` e
carrega de forma lazy só o que precisa. Variáveis carregáveis: `TABLE_NAME`,
`INGEST_KEY_PARAMETER`, `READ_KEY_PARAMETER`, `DIAGNOSTIC_RETENTION_DAYS` (só
telemetry; deve ser int ≥ 1). `LOG_LEVEL` (padrão INFO) e `SERVICE_VERSION`
(padrão 0.0.0; o template define 0.1.0) são sempre opcionais. Uma variável
obrigatória ausente levanta `RuntimeError` → surge como 500 (má configuração
barulhenta). Parâmetros de infra ficam em `template.yaml` (`Stage`, nomes de
chave, `DiagnosticRetentionDays`, `LogRetentionDays`, limites de throttle).

**Diferenças local vs demo vs cloud.** *Local*: `.env`/env controla thresholds,
caminhos, probes; sync desligada a menos que `API_BASE_URL` seja setada. *Demo*
(`DEMO_SYNC_SETTINGS`, `Thresholds()`, `DEMO_DEVICE_ID`): thresholds, sync
settings e identidade são **constantes** para que `.env` não mude a saída; o
endpoint é o inalcançável `demo.invalid`. *Cloud*: configurada inteiramente por
env vars da Lambda vindas do template SAM; sem `.env`.

---

## 15. Known Boundaries (confirmado)

Cada item foi confirmado contra o repo (limitações do README, engineering report,
template, código):

- **Não implantado na AWS.** O repo contém SAM + scripts, mas nada implanta automaticamente; validação é só `cfn-lint` offline (`sam validate` não roda — SAM CLI ausente).
- **Sem Serviço Windows / tarefa agendada.** `run` é um laço em foreground; não há serviço/instalador.
- **Sem execução remota de comandos.** A nuvem nunca instrui o agente; coletores/consultas de plataforma são somente-leitura.
- **Sem dashboard / UI web.** Só a CLI + a read API.
- **Sem alarmes SNS / CloudWatch.** Métricas são emitidas; alarmes/notificações são trabalho futuro.
- **Sem coletores Linux/macOS.** Coletores são Windows-first (`platform_support` é CIM Windows); a arquitetura permite outros depois.
- **Sem credenciais por dispositivo / mTLS.** Uma única chave de ingest compartilhada (ADR-007); atribuição depende de `sourceIp`.
- **Sem back-fill de execuções com sync desabilitada.** Execuções gravadas com sync desligada ficam só locais (ADR-001).
- **Sem point-in-time recovery** na tabela por padrão (trade-off de custo, ADR-003).
- **Sem packet loss por ICMP cru.** "Packet loss" é a taxa de falha de probe TCP (não exige privilégios de admin).

---

## 16. AWS Certification Study Map

Relação entre o projeto e o conhecimento de certificação (sem ranking entre
certificações). Certs abreviadas: **SAA** = Solutions Architect Associate,
**DVA** = Developer Associate, **CloudOps** = CloudOps/SysOps Engineer.

| Componente do projeto | Conceito AWS | Conceito técnico | Certificação(ões) | Arquivo | O que preciso saber explicar |
|---|---|---|---|---|---|
| HTTP API Gateway | HTTP API vs REST API, stages, throttling, access logs | Entrada pública HTTPS, rate/burst, roteamento | SAA, DVA, CloudOps | `infrastructure/template.yaml` (`HttpApi`) | Por que HTTP API em vez de REST aqui; como o throttling limita custo; o que o access log captura |
| Lambda ×4 | Computação orientada a eventos, integração proxy, cold starts | Handlers stateless, memória/arquitetura, timeout | SAA, DVA | `src/cloud/handlers/*`, `src/cloud/http.py` | Fluxo requisição→handler; por que 128 MB/arm64/10 s; caching de container quente |
| DynamoDB | Single-table design, GSI, TTL, escritas condicionais | Modelagem PK/SK, índice esparso, idempotência | SAA, DVA | `src/cloud/repository.py`, `docs/data-model.md` | Os 7 padrões de acesso; como `event_id`+hash dá exatamente-uma-vez; expiração por TTL |
| CloudWatch | Logs vs Metrics, EMF, retenção | Logs estruturados, métricas custom, dimensões | CloudOps, DVA | `src/cloud/metrics.py`, `docs/observability.md` | Como o EMF faz uma métrica de uma linha de log; por que `device_id` não é dimensão; cobrança |
| SSM Parameter Store | SecureString, decrypt KMS, ARNs de parâmetro | Recuperação de segredo + cache | SAA, DVA, CloudOps | `src/cloud/auth.py`, params do template | SecureString vs Secrets Manager; `alias/aws/ssm`; cache tolerante a stale |
| IAM | Menor privilégio, políticas inline, assume-role | Ações escopadas a recurso, sem wildcards | SAA, DVA, CloudOps | papéis em `infrastructure/template.yaml` | Por que um papel por função; quais ações cada uma precisa e por quê |
| SAM / CloudFormation | IaC, transforms, intrínsecos, outputs | Infra declarativa, validação offline | DVA, CloudOps | `infrastructure/template.yaml`, `samconfig.toml` | Como o SAM expande para CloudFormation; `cfn-lint` vs `sam validate` |
| API Gateway → Lambda → DynamoDB | Pipeline de requisição serverless | Auth → validar → persistir → responder | SAA, DVA | handlers + repository | O caminho completo de um POST de telemetria |
| Fila de sync do agente | Confiabilidade / retries | Backoff+jitter, dead-letter, idempotência | DVA, CloudOps | `src/agent/sync/*`, `storage/queue.py` | Offline vs entregue-mas-falhou; por que offline não vira dead-letter |

---

## 17. Interview Knowledge Map

Perguntas que você deve conseguir responder depois de estudar o projeto. (Apenas
as perguntas — não as responda aqui.)

**Python**
- Por que o pipeline levanta um `ValueError` explícito em vez de `assert` para o invariante identidade/store?
- O que o `__repr__`/`__str__` do tipo `Secret` retorna, e por quê?
- Como `run_collector` garante que a falha de um coletor nunca aborta a execução?
- Por que `SyncSettings` é definido em `config/settings.py` e não em `sync/`?

**Backend**
- Como o decorator `@api_handler` centraliza auth + mapeamento de erro?
- Por que os handlers cacheiam settings/clients em globais de módulo?
- Qual é a ordem de processamento dentro de `/v1/telemetry` e por que essa ordem?

**HTTP**
- Quais status HTTP são transientes vs permanentes na classificação do cliente, e por que a ordem importa?
- Por que o transporte recusa redirects?
- O que torna uma resposta "malformada" e por que repeti-la é seguro?

**SQLite**
- O que o WAL muda entre leitores e o único escritor?
- Como as migrações são versionadas, e contra o que o `application_id` protege?
- Por que run, results e evento de fila são escritos em um `BEGIN IMMEDIATE`?

**Networking**
- O que o "packet loss" deste projeto de fato mede?
- Como o status de rede é classificado first-match, e o que dispara OFFLINE vs UNKNOWN?
- Por que a evidência de interface é só por contagem?

**Segurança**
- Por que um token bearer não-ASCII deve ser 401 e não 500?
- Como o higienizador de IP é preciso o suficiente para manter `C:\` e `16:42:03` mas redigir `fe80::1%12`?
- Quais dados nunca são enviados, e como isso é garantido (whitelist vs estrutural vs scrub)?

**AWS**
- Por que HTTP API em vez de REST API aqui?
- Por que `arm64`/128 MB/10 s, e quais os trade-offs?
- Onde ficam as chaves de API e como são descriptografadas?

**Serverless**
- O que acontece em um cold start para uma rota autenticada?
- Como o design mantém o custo ocioso quase-zero?

**DynamoDB**
- Explique as chaves single-table e o GSI1 esparso.
- Como o put condicional distingue duplicata de conflito?
- Como o TTL funciona e o que não tem TTL?

**IAM**
- Por que um papel por função em vez de um papel compartilhado?
- Quais ações DynamoDB cada função ganha, e quais deliberadamente lhe faltam?

**Testes**
- O que o teste de limite de import garante e por que importa?
- Como moto e o teste e2e com servidor HTTP local se complementam?
- Quais testes fixam as três correções MEDIUM?

**Arquitetura**
- Percorra uma execução de diagnóstico da leitura de hardware até um item no DynamoDB.
- Por que a sync é uma etapa separada do pipeline?
- O que acontece com um evento enfileirado durante uma queda de uma semana?

---

## 18. Developer Must Understand

Uma trilha de conhecimento (não um ranking de qualidade).

**MUST UNDERSTAND**
- O fluxo local completo: collect → diagnose → persist → enqueue, e que funciona offline.
- A máquina de estados da fila offline e o dono de cada transição (`storage/queue.py`).
- Retry/backoff/jitter e a regra de que abortos offline/auth/config não consomem o orçamento enquanto entregue-mas-falhou consome.
- Idempotência: `event_id` UUIDv7 + payload congelado + put condicional (duplicata vs conflito).
- O caminho API Gateway → Lambda → DynamoDB para um POST de telemetria, incluindo auth e validação.
- Menor privilégio IAM: um papel por função e por que cada permissão existe.
- As três correções MEDIUM (M1 guard de exclusão do demo, M2 auth 401-não-500, M3 scrub de IP + interface-por-contagem).

**SHOULD UNDERSTAND**
- O schema compartilhado como contrato único usado pelos dois lados.
- Carregamento + cache + tolerância a stale das SecureStrings do SSM.
- A tabela de classificação de respostas HTTP e os motivos de aborto.
- WAL, migrações e o marcador live/demo `application_id`.
- Métricas EMF, a dimensão `[Service,Function]` e a cobrança de métrica custom.
- O determinismo do modo demo e o isolamento de recursos.

**NICE TO UNDERSTAND**
- Codificação/validação de cursor e por que é vinculada ao dispositivo.
- A precedência de exit code (1 > 3 > 0) e o sleep interrompível.
- Geração de causas/evidências na classificação de rede.
- A lista de desvios-da-especificação em `docs/architecture.md`.

---

## 19. Review Sequence

Para cada fase: objetivo · arquivos · perguntas que você deve conseguir responder.

**Phase 1 — Documentation.** Objetivo: formar o modelo mental e o "porquê".
Arquivos: `README.md`, `docs/architecture.md`, `docs/decisions/ADR-00{1..7}`,
`docs/engineering-report.md`. Perguntas: Que problema o local-first resolve? Por
que serverless + DynamoDB + SAM? O que cada ADR decide e rejeita?

**Phase 2 — Local Agent.** Objetivo: entender coleta → persistência.
Arquivos: `agent/main.py`, `commands.py`, `pipeline.py`, `collectors/*`,
`diagnostics/*`, `storage/local_db.py`, `storage/queue.py`. Perguntas: Como
`run_collector` isola falhas? O que é escrito em uma transação? Quais são os
estados e transições da fila?

**Phase 3 — Synchronization.** Objetivo: entender entrega + confiabilidade.
Arquivos: `sync/serializer.py`, `sync/client.py`, `sync/retry.py`,
`sync/service.py`. Perguntas: O que é enviado e o que é higienizado? Como cada
desfecho HTTP é classificado? Por que um ciclo offline não vira dead-letter?

**Phase 4 — AWS Backend.** Objetivo: entender o lado nuvem.
Arquivos: `cloud/auth.py`, `cloud/handlers/*`, `cloud/http.py`,
`cloud/repository.py`, `cloud/cursor.py`, `infrastructure/template.yaml`.
Perguntas: Como a auth evita um 500 em entrada hostil? Quais são os padrões de
acesso e escritas condicionais? Quais permissões cada papel detém?

**Phase 5 — Tests.** Objetivo: ver o que de fato é provado.
Arquivos: `tests/unit/*`, `tests/integration/{test_sync_e2e,test_offline}.py`,
`tests/integration/test_handlers_moto.py`, `tests/quality/*`,
`tests/infra/test_template.py`. Perguntas: O que o teste de limite de import
garante? Quais testes fixam M1/M2/M3? Como o comportamento offline é verificado
sem rede?

**Phase 6 — Architecture Diagram.** Objetivo: internalizar o sistema inteiro
reconstruindo-o. Reconstrua a arquitetura **manualmente no draw.io usando ícones
oficiais da AWS** (API Gateway, Lambda, DynamoDB, CloudWatch, SSM, IAM),
espelhando `diagrams/architecture.mmd`. Perguntas: Você consegue desenhar o
domínio de confiança local vs o domínio AWS e cada seta (HTTPS Bearer,
Lambda→DynamoDB/SSM/CloudWatch) de memória?

---

## 20. Final Audit Checklist

Use depois da leitura. Você deve conseguir:

- [ ] Explicar o fluxo local completo (collect → diagnose → persist → enqueue) offline.
- [ ] Explicar a fila offline e cada transição de estado.
- [ ] Explicar retry/backoff/jitter e quando o orçamento de retry é (ou não) consumido.
- [ ] Explicar idempotência via `event_id` + hash de payload (duplicata vs conflito).
- [ ] Traçar um POST de telemetria por API Gateway → Lambda → DynamoDB.
- [ ] Explicar menor privilégio IAM por função e por que cada permissão existe.
- [ ] Explicar como as duas chaves SSM são armazenadas, descriptografadas e cacheadas.
- [ ] Explicar o que os principais testes provam (unit, moto, e2e, offline, quality gates).
- [ ] Explicar as três correções MEDIUM (M1 guard do demo, M2 401-não-500, M3 scrub + interface-por-contagem).
- [ ] Explicar WAL, migrações e o marcador live/demo `application_id`.
- [ ] Explicar métricas EMF, o conjunto de dimensões e a cobrança de métrica custom.
- [ ] Dizer o que o projeto NÃO faz (§15) sem chutar.
- [ ] Reconstruir a arquitetura no draw.io com ícones oficiais da AWS de memória.

---

## Source-of-Truth Verification

**Arquivos/documentos analisados (lidos por completo salvo nota).**
- Agente: `main.py`, `commands.py`, `pipeline.py`, `identity.py`, `demo.py`, `collectors/base.py`, `diagnostics/engine.py`, `diagnostics/network_diagnostics.py`, `diagnostics/rules.py` (parcial), `config/settings.py`, `storage/local_db.py`, `storage/queue.py`, `sync/{retry,client,service,serializer}.py`.
- Cloud: `auth.py`, `config.py`, `errors.py`, `http.py`, `metrics.py`, `repository.py`, `cursor.py`, `handlers/{health,device,telemetry,diagnostic,_support}.py`.
- Shared: `schemas/common.py` (e referências a `schemas/device.py`, `schemas/telemetry.py`).
- Infra/config: `infrastructure/template.yaml`, `pyproject.toml`, `.env.example`.
- Docs: `README.md`, `docs/{architecture,api,data-model,security,threat-model,observability,cost,engineering-report}.md`, `docs/decisions/ADR-001..007.md`, `diagrams/{architecture,data-flow,sync-state-machine}.mmd`.
- Testes (lidos): `tests/unit/agent/{test_demo,test_serializer}.py`, `tests/unit/cloud/test_auth.py`, `tests/integration/test_offline.py`; o restante percorrido pela lista de arquivos para a §13.
- Contexto de revisão: `.agents/tasks/design-review.md` (para o histórico de M1/M2/M3).
- Comandos de verificação executados (somente-leitura): `pytest --collect-only -q` → 357 testes; `pytest -q` → **357 passed**.

**Divergências encontradas (documentação vs implementação): nenhuma material.**
As três correções MEDIUM (M1/M2/M3) descritas em `.agents/tasks/design-review.md`
estão todas implementadas como descrito e verificadas contra o código e seus
testes. Pontos de precisão notados (consistentes, mas fáceis de ler errado):
- A regra do orçamento de retry está corretamente afirmada na ADR-005, em `observability.md` e na matriz de falhas: só abortos *comprovadamente não-entregues* (OFFLINE) e auth/config são não contabilizados; falhas de *entrega incerta* consomem o orçamento. A frase de alto nível do README "being offline … without consuming the retry budget" é precisa, mas omite essa nuance entregue-vs-não-entregue, que os docs mais profundos explicitam. Sinalizado aqui para que o leitor não generalize demais "qualquer falha de rede é grátis".
- O documento de revisão (`design-review.md`) descreve os problemas *pré-correção* (ex.: o conflito de identidade do demo no finding 4). O `demo.py` entregue os resolve (um `DEMO_DEVICE_ID` fixo inserido diretamente, `resolve_device_id` não chamado), então o documento de revisão é histórico, não uma descrição do comportamento atual.

**Pontos que precisam de revisão manual (tempo de deploy; não confirmáveis lendo
código offline).**
- Decrypt KMS das SecureStrings do SSM via `alias/aws/ssm` (sem statement explícito `kms:Decrypt` no template; depende da policy da chave gerenciada).
- SAM resolvendo `CodeUri: ../src` e produzindo um artefato `arm64` funcional; o orçamento de 128 MB / 10 s da Lambda incluindo cold start do SSM.
- Logging de acesso do HTTP API exigindo o service-linked role do API Gateway no primeiro deploy.
- Se o boto3 embutido no runtime `python3.13` suporta `ReturnValuesOnConditionCheckFailure` (data de 2023; risco baixo, não verificado contra a imagem do runtime).

**Comportamento que não pôde ser confirmado só por leitura.** Formatos reais de
saída de PowerShell/CIM do Windows e localização do `ping` são cobertos por
fixtures, não por uma execução Windows ao vivo nesta revisão; o comportamento AWS
real (throttling fazendo efeito, latência de cold-start, timing de TTL) não é
exercitado porque nada está implantado. Todas as afirmações sobre AWS aqui são
lidas de `infrastructure/template.yaml` e dos handlers, não de uma stack em
execução.
