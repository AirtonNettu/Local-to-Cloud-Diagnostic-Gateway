# Relatório de engenharia

> Idioma: Português (Brasil) · [English](engineering-report.md)

## Resumo da arquitetura

Um agente Python voltado primeiro ao Windows roda um pipeline `collect →
diagnose → evaluate → persist (+ enqueue) → report` inteiramente offline,
armazenando cada execução em SQLite. A telemetria selecionada e minimizada é
enfileirada localmente e sincronizada com um backend serverless da AWS (HTTP API
Gateway → quatro funções Lambda → DynamoDB de tabela única, com logs/métricas do
CloudWatch e chaves armazenadas no SSM). O código do agente, da nuvem e
compartilhado são três pacotes em `src/`; o schema compartilhado é o contrato da
API que ambos os lados usam.

## Componentes

- **agent**: CLI, pipeline, coletores, um módulo de plataforma do Windows somente
  leitura, diagnósticos (probes, rules, health), armazenamento SQLite, a fila e o
  serviço de sincronização, configuração e logging.
- **cloud**: parsing de HTTP + o mapeamento de erros `@api_handler`, auth Bearer
  com dois escopos apoiados no SSM, o repositório do DynamoDB, métricas EMF e
  quatro handlers (health, device, telemetry, diagnostic).
- **shared**: modelos imutáveis, validadores escritos à mão e utilitários de
  UUIDv7 / tempo-ISO / log-JSON.

## Fluxo de dados

Leituras de hardware viram fatos tipados de coletor, o motor as transforma em
checks/alerts/metrics e um status geral, o resultado é persistido e (se a
sincronização estiver ativa) enfileirado como um payload congelado e com IPs
removidos. Um ciclo de sincronização entrega lotes empacotados por bytes sobre
HTTPS com um token Bearer; o Lambda autentica, valida contra o schema
compartilhado e escreve um item idempotente por `event_id` no DynamoDB. Logs e
métricas EMF vão para o CloudWatch.

## Segurança

HTTPS com verificação de certificado e sem redirecionamentos; uma chave Bearer
com escopos `ingest` e `read` armazenada como SSM SecureStrings e comparada em
tempo constante em bytes; uma role IAM de menor privilégio por função, sem ações
curinga; validação estrita de schema; minimização de dados e remoção de IPs antes
do envio. Veja [security.pt-BR.md](security.pt-BR.md) e o
[modelo de ameaças](threat-model.pt-BR.md).

## Confiabilidade

Local-first: todo comando local funciona sem rede. A fila de sincronização é
durável com um backoff limitado e com jitter e um estado DEAD_LETTER. Estar
offline registra uma tentativa `OFFLINE` sem consumir o orçamento de
retentativas, então uma queda longa nunca manda um evento para dead-letter; a
sincronização retoma no primeiro ciclo após a conectividade voltar. A recuperação
de travamento reivindica leases `SYNCING` expirados. A ingestão é idempotente,
então retentativas e duplicatas armazenam exatamente um item.

## AWS

HTTP API Gateway (entrada pública barata e de baixa latência), Lambda (computação
sem estado por rota), DynamoDB (chave-valor serverless com TTL), SSM Parameter
Store (SecureStrings gratuitas), CloudWatch (logs + métricas EMF). Cada um é
justificado em [architecture.pt-BR.md](architecture.pt-BR.md).

## Custo

Pay-per-use com padrões conservadores: DynamoDB sob demanda, funções `arm64` de
128 MB, retenção de log de 14 dias, TTL nos eventos e um pequeno conjunto fixo de
métricas EMF com uma dimensão de baixa cardinalidade. Veja [cost.pt-BR.md](cost.pt-BR.md),
incluindo a nota de que métricas customizadas EMF são cobradas por nome ×
dimensão por mês (~10–12 métricas cobráveis em meses ativos).

## Testes

Tudo é verificado localmente sem conta AWS: testes unitários em agente, nuvem e
compartilhado; testes de integração da nuvem com moto invocando os handlers reais
com eventos v2 do API Gateway; um teste de ponta a ponta do cliente de
sincronização do agente contra os handlers reais sobre um `ThreadingHTTPServer`
local; cenários offline; asserções de infraestrutura no template SAM; e portões
de qualidade (fronteiras de import, vazamento de segredo, estrutura de
diagramas/ADR).

Resultados da execução final de verificação no `.venv` do projeto (Python
3.14.6, Windows PowerShell 5.1):

```text
pytest:     357 passed in ~55s
ruff check: All checks passed!
mypy src:   Success: no issues found in 65 source files
cfn-lint:   infrastructure/template.yaml passa (sem achados).
```

Os dois testes de qualidade antes pulados (`test_diagrams_in_sync` e
`test_adr_structure`) agora rodam e passam, porque os diagramas e ADRs que esta
feature adiciona existem. A linha de base antes desta feature era 355 passed, 2
skipped; adicionar os diagramas e ADRs converte esses dois skips em passes (357
passed, 0 skipped). `cfn-lint` roda como `cfn-lint infrastructure/template.yaml`
porque o pacote fixado expõe um console script em vez de uma entrada de módulo
`-m cfnlint`.

## Limitações conhecidas

- Coletores apenas para Windows; a arquitetura permite outras plataformas depois.
- Uma única chave de ingestão compartilhada (sem credenciais por dispositivo nem
  mTLS).
- Sem dashboard web, alertas ou comandos remotos.
- Execuções registradas com a sincronização desativada não são reprocessadas.
- `sam validate` não é executado aqui (a SAM CLI não está instalada); `cfn-lint`
  é usado para validação offline da IaC.

## Melhorias futuras

Credenciais por dispositivo, um authorizer do Lambda, um dashboard de leitura,
alarmes SNS/CloudWatch, coletores para Linux/macOS e point-in-time recovery para a
tabela.

# O que a pessoa desenvolvedora deve entender

Antes de apresentar este projeto, esteja confortável para explicar cada um
destes itens e onde ele aparece no código:

- **Módulos, classes, funções, type hints e exceções do Python**: o layout de
  pacotes em `src/`, as dataclasses imutáveis em `shared/models`, os resultados
  tipados dos coletores e as hierarquias de exceção em `cloud/errors.py` e
  `agent/sync/client.py`.
- **HTTP, REST, JSON, códigos de status HTTP**: o contrato `/v1` em
  [api.pt-BR.md](api.pt-BR.md) e a tabela ordenada de classificação de resposta
  em `agent/sync/client.py`.
- **API Gateway, Lambda, DynamoDB, IAM, CloudWatch**: os quatro handlers, o
  design de tabela única em [data-model.pt-BR.md](data-model.pt-BR.md), as roles
  por função no template SAM e as métricas EMF.
- **Autenticação e autorização**: o modelo Bearer de dois escopos em
  `cloud/auth.py` (comparação de bytes em tempo constante, chaves apoiadas no
  SSM).
- **SQLite, filas, retentativas, idempotência**: o schema local, a máquina de
  estados da fila em `agent/storage/queue.py`, a política de backoff e a
  idempotência por put condicional em `cloud/repository.py`.
- **Observabilidade**: logging JSON estruturado com redação e métricas EMF
  ([observability.pt-BR.md](observability.pt-BR.md)).
- **Edge computing e arquitetura serverless**: por que os diagnósticos rodam
  localmente e o backend é sem estado e pay-per-use (ADR-001, ADR-002).
- **Infraestrutura como código**: o template SAM e a validação offline com
  `cfn-lint` (ADR-006).
- **Diagnósticos de rede, DNS, TCP/IP**: os probes e a classificação em
  `agent/diagnostics` e a nota sobre taxa de falha de probes TCP em
  [architecture.pt-BR.md](architecture.pt-BR.md).
