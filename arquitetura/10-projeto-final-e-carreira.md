# 10 — Projeto final e próximos passos

> [⟵ Índice](README.md) · Anterior: [09](09-nuvem-e-solucoes.md)

---

## Hora de juntar tudo

Você chegou ao fim da trilha. Os módulos 01-09 deram a base; este módulo é sobre
**consolidar** com um projeto real do começo ao fim e traçar a **carreira** daqui
pra frente.

A verdade honesta: ler esta trilha não te faz arquiteto. **Aplicá-la, repetidas
vezes, em problemas reais, com decisões documentadas, faz.** Este módulo é o
ponto de virada do "estudei" pro "pratico".

---

## O projeto final: evoluir o `aws-cost-monitor`

Nada prova aprendizado como pegar um projeto e levá-lo adiante aplicando o que
você estudou. Aqui está um roteiro que exercita toda a trilha, em ondas de
dificuldade crescente. Faça **sozinho**, com o método do `../../APRENDA.md` e os
passos do `../../IMPLEMENTAR.md`.

### Onda 1 — Fundamentos de código (módulos 02, 03)
- [ ] Adicione **type hints** a todos os módulos de `src/`.
- [ ] Troque os `dict` por **dataclasses** (`CostAnalysis`, `Comparison`,
  `Alert`). Contrato explícito (módulo 06).
- [ ] Troque `print` por **`logging`** com níveis (módulo 07).
- **Entregue:** um commit por item, cada um com os testes passando.

### Onda 2 — Design e padrões (módulos 03, 04)
- [ ] Crie a abstração **`AIInterpreter`** (interface) e faça `LlamaInterpreter`
  implementá-la. Inversão de dependência de verdade.
- [ ] Adicione uma **`Factory`** que escolhe o interpretador pela config.
- [ ] Escreva um **ADR** (módulo 08) registrando a decisão de abstrair a IA.
- **Entregue:** o `main` passa a depender da interface, não do Llama. Prove com
  um teste que usa um interpretador falso (mock) no lugar do Llama.

### Onda 3 — Qualidade e dados (módulos 06, 07)
- [ ] Implemente a **paginação** do Cost Explorer (hoje lê só a 1ª página — é um
  bug latente em contas grandes).
- [ ] Adicione um **teste de integração** (coleta mockada + análise + relatório).
- [ ] Configure **CI** rodando o `pytest` (veja `../ci-and-env-explained.md`).
- **Entregue:** badge de CI verde no README.

### Onda 4 — Solução de nuvem (módulos 05, 09)
- [ ] Desenhe (C4, módulo 08) a versão **serverless** do sistema.
- [ ] Implemente a **persistência** com um `ReportRepository` (Repository, módulo
  04) — comece em arquivo, deixe pronto pra trocar por S3/banco.
- [ ] Escreva um documento de solução: o desenho, as escolhas, os trade-offs, o
  custo estimado. Esse documento **é** um artefato de Arquiteto de Soluções.
- **Entregue:** um `docs/solucao-serverless.md` que você conseguiria apresentar
  numa entrevista.

> Ao terminar as quatro ondas, você terá um projeto de portfólio que demonstra,
> na prática, cada camada desta trilha — de código limpo a desenho de solução de
> nuvem. Vale mais que qualquer certificado sozinho.

---

## Como continuar aprendendo depois

A trilha acaba; o aprendizado não. O que mantém o crescimento:

1. **Leia código bom.** Projetos open source pequenos e bem-feitos ensinam mais
   que tutoriais. Leia pra perguntar "por que eles decidiram assim?".
2. **Construa coisas de verdade.** Cada projeto novo é um problema de arquitetura.
   Comece simples (monolito modular), evolua quando doer.
3. **Documente suas decisões.** Mantenha ADRs nos seus projetos. Reler decisões
   antigas é como você percebe seu próprio crescimento.
4. **Ensine.** Explicar um conceito pra alguém (ou num post) expõe os buracos no
   seu entendimento como nada mais.
5. **Participe de revisões.** Pedir e dar code review te expõe a decisões
   diferentes das suas — a forma mais rápida de maturar julgamento.

---

## Mapa de carreira

```
Dev Júnior
   │  (foco: escrever código que funciona, aprender a base)
   ▼
Dev Pleno
   │  (foco: qualidade, autonomia, decisões de design em módulos)
   ▼
Dev Sênior
   │  (foco: decisões que afetam o sistema, mentoria, trade-offs)
   ├──────────────► Arquiteto de Software
   │                (foco: estrutura de um ou mais sistemas, padrões, qualidade)
   │
   └──────────────► Arquiteto de Soluções
                    (foco: sistemas + nuvem + negócio, desenho de soluções)
```

Não é uma escada rígida — muita gente transita entre os dois tipos de arquiteto.
A base (módulos 01-08) é **comum aos dois**. A diferença é o foco: software olha
pra dentro, soluções olha pra fora e pro negócio (módulo 09).

### O que te leva de um degrau ao outro

Não é tempo de casa. É **escopo de impacto das suas decisões**:
- Júnior decide dentro de uma função.
- Pleno decide dentro de um módulo.
- Sênior decide dentro de um sistema.
- Arquiteto decide entre sistemas e pro futuro.

Cresça o escopo das decisões que você consegue tomar **e justificar**, e o título
segue.

---

## Certificações (úteis, com ressalva)

Certificações ajudam a **estruturar o estudo** e **sinalizar conhecimento** no
mercado — especialmente pra nuvem. Mas elas comprovam que você sabe responder
provas, não que sabe arquitetar. **Projeto + certificação** é imbatível;
certificação sozinha, não.

Caminho comum pra quem mira AS em nuvem (ordem sugerida):
1. **Fundamentos de nuvem** (ex.: AWS Cloud Practitioner / Azure Fundamentals) —
   o vocabulário do módulo 09, formalizado.
2. **Associate de arquitetura** (ex.: AWS Solutions Architect Associate) — desenho
   de soluções, os pilares na prática.
3. **Profissional/especialidade** — depois de experiência real.

> Estude pra certificação **construindo**, não só decorando. O desenho serverless
> do módulo 09 cobre metade do conteúdo de uma prova de arquitetura associate —
> porque é o mesmo raciocínio.

---

## Palavra final

Você começou esta trilha, possivelmente, sabendo pouco de arquitetura. Se fez os
exercícios, agora você:

- entende que arquitetura é **decisão e trade-off**, não "a forma certa";
- enxerga **acoplamento, coesão e dependências** em qualquer código;
- conhece os **princípios, padrões e estilos** e, mais importante, **quando NÃO
  usá-los**;
- sabe cuidar de **dados, integração, qualidade e observabilidade**;
- sabe **comunicar e defender** decisões com diagramas e ADRs;
- entende o papel do **Arquiteto de Soluções** e consegue desenhar uma solução de
  nuvem simples.

Isso é a fundação de um arquiteto júnior. O que falta — e só o tempo e a prática
dão — é **repetição em problemas reais, cada vez maiores, com decisões cada vez
mais conscientes**.

> A diferença entre quem leu sobre arquitetura e quem é arquiteto é uma só:
> **o segundo decidiu, errou, documentou e aprendeu — muitas vezes.** Vá decidir.
> Comece pela Onda 1. 🚀

---

> [⟵ Voltar ao índice da trilha](README.md)
