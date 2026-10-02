# ADR-001: Diagnósticos local-first

> Idioma: Português (Brasil) · [English](ADR-001-local-first.md)

Status: aceito.

## Context

O agente diagnostica máquinas que podem elas mesmas ter conectividade degradada
ou ausente. Um design dependente da nuvem deixa de ser útil exatamente quando é
mais necessário, e enviar antes de persistir arrisca perder resultados durante
uma indisponibilidade.

## Decision

Diagnósticos, avaliação de saúde e persistência rodam inteiramente no host local
sem dependência de rede. Todo comando local (`hardware`, `network`, `health`,
`scan`, `status`, `queue`, `demo`) funciona offline. A sincronização é um passo
separado e opcional que lê uma fila já persistida; suas falhas nunca alteram o
resultado do diagnóstico. Persistência e enfileiramento ocorrem em uma única
transação local antes de qualquer sincronização.

## Alternatives

- **Cloud-first (enviar e depois armazenar)**: caminho de dados mais simples, mas
  perde dados durante quedas e acopla diagnósticos à conectividade. Rejeitado.
- **Apenas nuvem (sem armazenamento local)**: nenhuma capacidade offline.
  Rejeitado.

## Consequences

- O agente é útil em uma máquina isolada; resultados nunca são perdidos.
- Exigem-se uma fila local durável e uma máquina de estados de sincronização
  (ADR-005).
- Execuções registradas com a sincronização desativada ficam apenas locais e não
  são reprocessadas, o que é uma escolha deliberada de minimização de dados.
