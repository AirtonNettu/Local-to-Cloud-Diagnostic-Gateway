# ADR-002: Backend serverless

> Idioma: Português (Brasil) · [English](ADR-002-serverless-backend.md)

Status: aceito.

## Context

O backend ingere rajadas pequenas e esporádicas de telemetria de poucos
dispositivos e deve custar quase nada quando ocioso. É um projeto de portfólio
mantido por uma pessoa, então o overhead operacional deve ser mínimo.

## Decision

Usar um backend serverless da AWS: HTTP API Gateway na frente de quatro funções
Lambda pequenas, com DynamoDB para armazenamento, SSM para segredos e CloudWatch
para observabilidade. Não há servidores, contêineres ou capacidade a gerenciar.

## Alternatives

- **Contêineres (ECS/Fargate) ou EC2**: custo sempre ativo e patching para uma
  carga de baixo volume. Rejeitado.
- **Uma única Lambda monolítica**: roteamento mais simples, mas uma role IAM
  ampla demais; roles por função dão menor privilégio. Rejeitado.

## Consequences

- Custo ocioso quase nulo; o custo escala com requisições (veja [cost.pt-BR.md](../cost.pt-BR.md)).
- Cada função recebe sua própria role de menor privilégio.
- O design é específico da AWS; portabilidade é trocada por simplicidade.
- Cold starts são aceitáveis para um caminho de ingestão horário e assíncrono.
