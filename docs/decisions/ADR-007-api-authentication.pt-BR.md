# ADR-007: Autenticação da API

> Idioma: Português (Brasil) · [English](ADR-007-api-authentication.md)

Status: aceito.

## Context

A API precisa de uma autenticação simples de operar para um projeto de autor
único, que separe acesso de escrita e de leitura, mantenha segredos fora de
código e logs e seja segura para comparar contra entrada hostil. Credenciais por
dispositivo e um authorizer completo são mais do que a v1 precisa.

## Decision

Usar uma chave de API Bearer com dois escopos: `ingest` (agentes escrevem) e
`read` (operadores leem). Ambas as chaves são SSM SecureStrings, carregadas com
uma única chamada `GetParameters(WithDecryption=True)`, cacheadas por cinco
minutos e mantidas (obsoletas) se um refresh falhar, para que a rotação não cause
indisponibilidade. O token é parseado de forma defensiva e comparado em bytes com
`hmac.compare_digest`; ambas as comparações de escopo sempre rodam para que o
tempo não revele nada, e um token não-ASCII é um 401, não um 500. A imposição de
escopo vive no decorator `@api_handler`.

## Alternatives

- **Um authorizer do Lambda / Cognito / IAM SigV4**: mais forte, mas mais pesado
  de operar do que um modelo de duas chaves precisa para a v1. Adiado para
  trabalho futuro.
- **Uma única chave para todas as rotas**: sem separação entre escrita e leitura.
  Rejeitado.
- **Credenciais por dispositivo**: melhor atribuição, mas mais gestão de chaves;
  um risco residual documentado, adiado.

## Consequences

- Operação simples: dois parâmetros a provisionar e rotacionar.
- Uma chave de ingestão vazada pode forjar IDs de dispositivo até ser
  rotacionada; o `sourceIp` no log de acesso é a evidência de atribuição (veja
  [security.pt-BR.md](../security.pt-BR.md) e o
  [modelo de ameaças](../threat-model.pt-BR.md)).
- Comparação em tempo constante e parsing estrito tornam a auth segura contra
  headers hostis.
