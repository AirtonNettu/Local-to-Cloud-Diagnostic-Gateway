# ADR-003: Escolha do banco na nuvem (DynamoDB)

> Idioma: Português (Brasil) · [English](ADR-003-database-choice.md)

Status: aceito.

## Context

O armazenamento na nuvem deve ser serverless, pay-per-use, durável e suportar um
conjunto pequeno e bem conhecido de padrões de acesso por chave (registrar/ler um
dispositivo, listar dispositivos, ingerir um evento idempotente, ler diagnósticos
recentes). Deve expirar dados antigos automaticamente e evitar planejamento de
capacidade.

## Decision

Usar o DynamoDB com um design de tabela única: perfis de dispositivo e eventos de
diagnóstico compartilham uma partição por dispositivo (`PK = DEVICE#<id>`), um
GSI1 esparso responde "listar dispositivos", e um atributo de TTL expira eventos.
A cobrança sob demanda (PAY_PER_REQUEST) é usada. A idempotência é um `PutItem`
condicional em `event_id` com um hash de payload armazenado.

## Alternatives

- **Relacional (RDS/Aurora Serverless)**: consultas mais ricas, mas custo ocioso
  maior e mais superfície operacional do que os padrões de acesso exigem.
  Rejeitado.
- **Múltiplas tabelas DynamoDB**: mais itens a gerenciar e leituras entre
  tabelas; o design de tabela única cobre todos os padrões de acesso. Rejeitado.

## Consequences

- Os padrões de acesso são fixados pelo design de chaves (documentado em
  [data-model.pt-BR.md](../data-model.pt-BR.md)); novos padrões podem exigir um
  novo GSI.
- Armazenamento exatamente-uma-vez via escritas condicionais; duplicatas e
  conflitos são explícitos.
- Point-in-time recovery fica desligado por padrão como trade-off de custo.
