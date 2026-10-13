# 05 — Camadas e estilos de arquitetura

> [⟵ Índice](README.md) · Anterior: [04](04-padroes-de-projeto.md) · Próximo: [06 — Dados, APIs e integração](06-dados-apis-integracao.md)

---

## Estilo arquitetural: a forma geral do sistema

Se os padrões (módulo 04) são soluções pra problemas pontuais, um **estilo
arquitetural** é a **forma geral** do sistema inteiro — como ele é organizado em
alto nível. Aqui a gente dá zoom out: não mais funções e classes, mas blocos
grandes e como eles se dividem.

Vou apresentar os estilos do mais simples ao mais complexo, com o foco mais
importante: **quando usar e quando NÃO usar cada um.**

---

## Monolito

**O que é:** todo o sistema roda como uma única aplicação, um processo só.
O `aws-cost-monitor` é um monolito (um programa Python que faz tudo).

**A favor:**
- Simples de desenvolver, rodar e depurar — tudo num lugar.
- Sem complexidade de rede entre partes.
- Perfeito pra começar e pra sistemas pequenos/médios.

**Contra:**
- Pra escalar, você escala o bloco inteiro, mesmo que só uma parte precise.
- Com o tempo, se mal organizado, vira um "monolito espaguete".

> **Verdade que te poupa anos:** monolito **não** é palavrão. A maioria dos
> sistemas deveria começar como um monolito bem organizado. "Comece monolito,
> quebre em serviços só quando a dor justificar" é conselho de gente experiente.

### Monolito modular

A versão madura do monolito: um processo só, mas **internamente dividido em
módulos bem separados** (como o `aws-cost-monitor`, com suas camadas `aws`,
`analysis`, `ai`, `reports`). Você tem a simplicidade de um monolito com a
organização que permite, um dia, extrair um módulo pra um serviço separado.

---

## Arquitetura em camadas

**O que é:** organizar o sistema em camadas horizontais, cada uma com um papel,
onde cada camada só conversa com a vizinha. O clássico:

```
Apresentação   (interface com o usuário / API)
      ↓
Aplicação      (orquestra o caso de uso)
      ↓
Domínio        (regras de negócio)
      ↓
Infraestrutura (banco, APIs externas, arquivos)
```

**No `aws-cost-monitor`**, dá pra enxergar camadas:
- *Infra/coleta:* `cost_explorer.py` (fala com a AWS).
- *Domínio:* `cost_analyzer.py` + `finops_rules.py` (as regras de verdade).
- *Aplicação:* `main.py` (orquestra o fluxo).
- *Apresentação:* `report_generator.py` (como o resultado é mostrado).

**A regra de ouro das camadas:** as dependências apontam **pra baixo** (ou pra
dentro). A apresentação conhece o domínio; o domínio **não** conhece a
apresentação. Isso mantém a regra de negócio pura e reutilizável.

---

## Arquitetura hexagonal (Ports & Adapters)

**O problema que resolve:** nas camadas tradicionais, o domínio ainda tende a
depender da infraestrutura (o cálculo "sabe" que os dados vêm de um banco). A
hexagonal corta isso de vez.

**A ideia:** o **núcleo** (regras de negócio) fica no centro, sem conhecer o mundo
externo. Ele define **portas** (interfaces) do que precisa. O mundo externo
(banco, API, UI) se conecta por **adaptadores** que encaixam nessas portas.

```
        [ UI ]      [ API ]          ← adaptadores de entrada
            \        /
          (porta de entrada)
                |
        [ NÚCLEO: domínio ]           ← não conhece nada externo
                |
          (porta de saída)
            /        \
      [ Banco ]   [ Llama/AWS ]       ← adaptadores de saída
```

**Ligando ao que você já viu:** isto é a **inversão de dependência** (módulo 03)
aplicada ao sistema inteiro. O `cost_explorer` já é um **adaptador** de saída pra
AWS (módulo 04). Se você criar a interface `AIInterpreter`, ela vira uma **porta**
de saída, e `LlamaInterpreter` o adaptador. Você estaria caminhando pra uma
arquitetura hexagonal sem perceber.

**Quando usar:** sistemas com regras de negócio ricas que precisam ser testáveis
e independentes de tecnologia. **Quando não:** scripts simples — seria peso morto.

---

## Arquitetura orientada a eventos (event-driven)

**O que é:** as partes se comunicam **publicando e reagindo a eventos**, em vez
de se chamarem diretamente. "Algo aconteceu" → quem se importa reage.

**A favor:**
- Desacoplamento forte: o emissor não conhece os receptores (lembra do Observer,
  módulo 04).
- Escala e resiliência: dá pra enfileirar eventos, processar depois, adicionar
  novos reatores sem tocar no emissor.

**Contra:**
- Fluxo mais difícil de seguir ("quem reagiu a quê?").
- Depuração e consistência ficam mais complexas.

**Gancho no projeto:** o "sistema de alertas" + serverless do roadmap é
exatamente isso: um alerta de custo vira um evento (EventBridge), e notificadores
(SNS, e-mail) reagem. Módulo 09 aprofunda.

---

## Microsserviços

**O que é:** o sistema é dividido em **vários serviços pequenos e independentes**,
cada um com sua responsabilidade, seu banco, seu deploy, conversando por rede
(APIs/eventos).

**A favor:**
- Cada serviço escala e é implantado sozinho.
- Times independentes tocam serviços diferentes.
- Falha isolada: um serviço cai sem derrubar os outros (se bem feito).

**Contra (e são grandes):**
- Complexidade enorme: rede, latência, falhas parciais, consistência distribuída,
  monitoramento, deploy coordenado.
- Difícil de depurar e caro de operar.

> **O erro mais comum da indústria:** começar com microsserviços "porque é
> moderno". A maioria dos times não tem o problema que microsserviços resolvem
> (escala organizacional e técnica massiva) — só herdam a complexidade. **Monte
> microsserviços quando a dor do monolito for real e medida**, não por moda.

---

## Como escolher um estilo (o raciocínio do arquiteto)

Não existe "melhor estilo". Existe o adequado, decidido pelas perguntas do módulo
01 somadas a estas:

- **Qual o tamanho e a complexidade real do problema?** (Pequeno → monolito.)
- **Preciso escalar partes independentemente?** (Sim e comprovado → considerar
  serviços.)
- **Quantos times vão trabalhar nisso?** (Muitos times → separação ajuda.)
- **Qual a tolerância à complexidade operacional?** (Baixa → mantenha simples.)
- **O que é caro de mudar depois?** (Sempre volte a essa.)

> Receita segura pra 90% dos casos: **comece com um monolito modular bem feito**
> (camadas claras, baixo acoplamento). Ele te dá velocidade agora e a opção de
> extrair serviços depois, se e quando a dor justificar. O `aws-cost-monitor`
> está exatamente nesse ponto saudável.

---

## Prática do módulo

1. **Classifique o projeto.** Escreva: o `aws-cost-monitor` é um monolito, mas
   modular. Liste as evidências de que ele é modular (as camadas) e aponte um
   módulo que seria o candidato natural a virar um serviço separado no futuro.
   (Dica: a coleta ou a IA.)

2. **Desenhe a versão hexagonal.** Pegue o projeto e redesenhe-o como hexágono:
   o que é o núcleo? Quais são as portas? Quais os adaptadores de entrada e saída?
   Não precisa codar — o desenho é o exercício.

3. **Debata um estilo.** Imagine que o `aws-cost-monitor` virou um produto SaaS
   com 10.000 clientes. Escreva um parágrafo argumentando a favor de quebrá-lo em
   serviços, e outro contra. Qual lado vence, no seu julgamento? Esse exercício
   de "defender os dois lados" é o que arquitetos fazem em reuniões.

4. **Encontre o over-engineering.** Descreva um cenário em que escolher
   microsserviços pra um projeto pequeno traria só dor. Liste três complexidades
   concretas que você herdaria sem necessidade.

---

> **Resumo:** o estilo é a forma geral do sistema. Monolito (comece aqui) →
> camadas (organize) → hexagonal (isole o núcleo) → event-driven (desacople no
> tempo) → microsserviços (só com dor real). A escolha é sempre trade-off guiado
> por contexto, nunca moda.
>
> Próximo: **[06 — Dados, APIs e integração](06-dados-apis-integracao.md)**.
