# 01 — O que é arquitetura, de verdade

> [⟵ Índice da trilha](README.md) · Próximo: [02 — Código e modularidade](02-codigo-e-modularidade.md)

---

## A definição que importa

Esqueça as definições cheias de jargão. Fique com esta:

> **Arquitetura de software é o conjunto de decisões difíceis de mudar depois.**

É isso. A linguagem que você usa, se o sistema é um bloco só ou vários serviços,
onde os dados moram, como as partes conversam — são decisões que, uma vez
tomadas, custam caro pra desfazer. Arquitetura é cuidar bem **dessas** decisões.

O código do dia a dia (o nome de uma variável, o corpo de uma função) é fácil de
mudar. A arquitetura é o que fica embaixo e segura tudo. Se ela for ruim, cada
mudança vira uma luta. Se for boa, o sistema aceita mudança sem desmoronar.

---

## Arquitetura é sobre trade-offs, não sobre "o certo"

O erro nº 1 de quem começa é procurar "a forma certa". Não existe. Existe a forma
**adequada ao seu contexto**, e toda escolha troca uma coisa por outra.

Exemplos de trade-offs reais:

- **Velocidade de entrega × robustez.** Um script rápido entrega hoje; um sistema
  bem estruturado demora mais mas aguenta anos.
- **Simplicidade × flexibilidade.** Código simples é fácil de ler; código
  flexível aceita mais casos, mas é mais complexo. Flexibilidade que você não vai
  usar é só complexidade.
- **Performance × clareza.** O código mais rápido raramente é o mais legível.
- **Custo × escala.** Uma arquitetura que aguenta milhões de usuários custa mais
  e é mais complexa que uma que aguenta mil.

> A pergunta do arquiteto nunca é "isso é certo?". É **"o que eu ganho e o que eu
> perco com isso, no MEU contexto?"**.

---

## As três perguntas que definem pensamento arquitetural

Treine fazer estas três perguntas sobre qualquer sistema:

1. **Custo de mudança:** se eu precisar mudar X, quantos lugares eu toco? Quanto
   mais localizado o impacto, melhor a arquitetura.
2. **Contenção de dano:** se a parte Y quebrar, o que mais cai junto? Boa
   arquitetura isola falhas.
3. **Testabilidade:** eu consigo testar uma parte sem ligar o sistema inteiro? Se
   não, as partes estão grudadas demais.

Essas três perguntas aparecem em TODA a trilha. Decore-as.

### Vendo no `aws-cost-monitor`

Olhe o projeto deste repositório com as três perguntas:

1. **Custo de mudança:** `boto3` só é importado em `src/aws/cost_explorer.py`. Se
   a AWS mudar a API, você toca **um** arquivo. Custo de mudança baixo — bom.
2. **Contenção de dano:** se o Llama (IA) cair, o relatório ainda sai (sem a
   interpretação). A falha ficou **contida** na camada opcional. Bom.
3. **Testabilidade:** o cálculo (`cost_analyzer.py`) é testado sem internet,
   porque não depende da AWS nem da IA diretamente. Bom.

Essas três respostas "boas" não são sorte — são consequência de decisões
arquiteturais que você vai aprender a tomar de propósito.

---

## Atributos de qualidade (os "-idades")

Quando alguém diz "quero um sistema bom", o arquiteto traduz "bom" em atributos
mensuráveis. Os principais:

| Atributo | Pergunta que ele responde |
|---|---|
| **Manutenibilidade** | É fácil mudar sem quebrar? |
| **Escalabilidade** | Aguenta crescer (mais usuários/dados)? |
| **Disponibilidade** | Fica no ar quando precisa? |
| **Desempenho** | Responde rápido o suficiente? |
| **Segurança** | Protege dados e acessos? |
| **Testabilidade** | Dá pra verificar que funciona? |
| **Observabilidade** | Dá pra enxergar o que está acontecendo em produção? |

O ponto crucial: **você não maximiza todos ao mesmo tempo.** Mais segurança
costuma custar desempenho; mais escalabilidade custa simplicidade. O arquiteto
descobre **quais atributos importam pra este sistema** e otimiza esses, aceitando
ser "ok" nos outros.

> Exemplo: um banco prioriza segurança e consistência acima de velocidade. Uma
> rede social prioriza disponibilidade e escala, e tolera dados ligeiramente
> desatualizados. Mesma palavra "bom", prioridades opostas.

---

## Requisitos funcionais × não-funcionais

- **Funcionais:** o que o sistema FAZ. "Gerar um relatório de custos."
- **Não-funcionais:** COMO ele faz, as qualidades. "O relatório sai em menos de 5
  segundos", "roda sem credenciais no código", "funciona mesmo sem a IA".

Iniciantes focam só no funcional ("fazer funcionar"). Arquitetos passam metade do
tempo nos não-funcionais — porque são eles que determinam se o sistema sobrevive
ao mundo real.

---

## O custo de errar cedo vs tarde

Uma decisão arquitetural ruim descoberta **no começo** custa quase nada —
é só mudar o rumo. A mesma decisão descoberta **depois de um ano** de código
construído em cima dela pode custar meses de retrabalho.

É por isso que arquitetos pensam antes de o time construir. Não é burocracia: é
porque mudar o alicerce de uma casa pronta é muito mais caro que mudar a planta.

> Mas cuidado com o extremo oposto: **"paralisia por análise"**. Você nunca terá
> informação completa. O arquiteto decide com o que tem, documenta a decisão (ver
> módulo 08, ADRs), e ajusta quando aprender mais. Decidir é melhor que travar.

---

## Prática do módulo

1. **Três perguntas, um sistema que você usa.** Pegue um app que você conhece
   (WhatsApp, um e-commerce). Tente responder: o que acontece se o servidor de
   mensagens cair? O que escala quando chegam mais usuários? Não precisa acertar —
   precisa treinar a pergunta.

2. **Trade-off escrito.** Pense no `aws-cost-monitor`: ele salva relatórios como
   arquivos soltos em `reports/`. Liste 2 vantagens e 2 desvantagens dessa
   decisão versus salvar num banco de dados. Qual você escolheria pra um projeto
   de portfólio? E pra uma empresa? Por quê?

3. **Atributos priorizados.** Para um app de banco e para um jogo online, ordene
   estes três atributos do mais pro menos importante: desempenho, segurança,
   disponibilidade. Justifique. Repare como a ordem muda — esse é o insight.

4. **Comece o caderno de decisões.** Registre a decisão do exercício 2 no formato
   Decisão / Porquê / Alternativa (ver o índice da trilha).

---

> **Resumo:** arquitetura é decidir o que é caro de mudar, aceitando trade-offs
> conscientes, guiado pelos atributos de qualidade que importam no contexto. As
> três perguntas — custo de mudança, contenção de dano, testabilidade — são a sua
> bússola.
>
> Próximo: **[02 — Código e modularidade](02-codigo-e-modularidade.md)**.
