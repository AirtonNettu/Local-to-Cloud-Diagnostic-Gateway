# Trilha de Arquitetura — do zero ao arquiteto júnior

> Uma trilha de estudo **completa e transferível** (não presa a nenhum projeto)
> para sair do início absoluto e chegar a **Arquiteto de Software** e **Arquiteto
> de Soluções Júnior**. Usa o projeto `aws-cost-monitor` como laboratório prático
> quando um conceito pede exemplo concreto, mas os conceitos valem para qualquer
> stack.
>
> Escrita para quem tem pouca experiência. Cada módulo tem **teoria enxuta**,
> **o porquê**, e **prática** — porque arquitetura só entra na cabeça quando você
> sente a dor que ela resolve.

---

## Como usar esta trilha

- **Siga a ordem.** Cada fase pressupõe a anterior. Pular queima etapa e deixa
  buracos que te travam depois.
- **Pratique antes de avançar.** Ao fim de cada módulo há exercícios. Faça com as
  mãos. Ler sem praticar não constrói arquiteto.
- **Mantenha um caderno de decisões.** A habilidade central do arquiteto é
  **decidir e justificar**. Treine escrevendo suas decisões e o porquê delas.
- **Ritmo sugerido:** 1 módulo a cada 1-2 semanas. A trilha inteira é de meses,
  não de dias. Isso é normal e é o ponto.

> Antes desta trilha, se você ainda está começando a programar, faça o
> `../../APRENDA.md` (método de estudo) e o `../../IMPLEMENTAR.md` (prática no
> código). Esta trilha assume que você já consegue ler e escrever código simples.

---

## O destino: o que faz cada papel

Entender aonde você quer chegar ajuda a estudar com direção.

| Papel | O que faz, em uma frase |
|---|---|
| **Desenvolvedor** | Escreve e mantém código que resolve um problema. |
| **Desenvolvedor sênior** | Faz o acima com qualidade e ajuda os outros a fazerem. |
| **Arquiteto de Software** | Decide a **estrutura interna** de um sistema: módulos, camadas, dependências, padrões. Garante que o sistema seja sustentável ao longo do tempo. |
| **Arquiteto de Soluções** | Decide **como múltiplos sistemas e serviços** (muitas vezes na nuvem) se combinam para resolver uma necessidade de negócio, equilibrando custo, segurança, escala e prazo. |

> Resumo cru: **Arquiteto de Software** olha pra dentro de um sistema;
> **Arquiteto de Soluções** olha pra como os sistemas se conectam no mundo real
> (nuvem, integrações, negócio). Os dois compartilham a mesma base — e é essa
> base que esta trilha constrói.

---

## Mapa da trilha

### Parte I — Fundamentos (a base de tudo)
- **[01 — O que é arquitetura, de verdade](01-fundamentos.md)**
  Decisões, trade-offs, custo de mudança, atributos de qualidade.
- **[02 — Pensar em código limpo e modular](02-codigo-e-modularidade.md)**
  Acoplamento, coesão, responsabilidade única, abstração, contratos.

### Parte II — Projetar sistemas
- **[03 — Princípios de design (SOLID e companhia)](03-principios-design.md)**
  SOLID sentido na pele, DRY, KISS, YAGNI, composição vs herança.
- **[04 — Padrões de projeto que importam](04-padroes-de-projeto.md)**
  Strategy, Adapter, Factory, Repository, Observer — com o problema que cada um
  resolve.
- **[05 — Camadas e estilos de arquitetura](05-estilos-arquiteturais.md)**
  Monolito, camadas, hexagonal/ports-and-adapters, event-driven, microsserviços
  — e quando (não) usar cada um.

### Parte III — Qualidade e operação
- **[06 — Dados, APIs e integração](06-dados-apis-integracao.md)**
  Modelagem, REST, contratos, versionamento, consistência.
- **[07 — Qualidade: testes, erros, observabilidade](07-qualidade-testes-observabilidade.md)**
  Pirâmide de testes, tratamento de falha, logs/métricas/traces.
- **[08 — Documentar e comunicar arquitetura](08-documentar-e-comunicar.md)**
  Diagramas C4, ADRs (registros de decisão), como defender uma decisão.

### Parte IV — Nuvem e soluções
- **[09 — Fundamentos de nuvem e arquiteto de soluções](09-nuvem-e-solucoes.md)**
  Modelos de serviço, pilares de boa arquitetura, custo, segurança, o papel do
  AS.
- **[10 — Projeto final e próximos passos](10-projeto-final-e-carreira.md)**
  Evoluir o `aws-cost-monitor` para serverless como estudo de caso completo +
  roteiro de carreira e certificações.

---

## Caderno de decisões (comece hoje)

Crie um arquivo seu (fora do repositório, se preferir) chamado `decisoes.md`. A
cada escolha técnica que fizer nos exercícios, registre três linhas:

```
Decisão: o que escolhi.
Porquê: a razão e o trade-off aceito.
Alternativa: o que descartei e por quê.
```

Esse hábito é, sozinho, metade do que torna alguém arquiteto. O resto é
repetição com consciência — que é o que esta trilha treina.

---

> **Próximo passo:** abra **[01 — O que é arquitetura, de verdade](01-fundamentos.md)**.
