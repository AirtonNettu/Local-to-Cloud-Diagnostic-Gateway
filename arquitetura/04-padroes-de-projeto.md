# 04 — Padrões de projeto que importam

> [⟵ Índice](README.md) · Anterior: [03](03-principios-design.md) · Próximo: [05 — Estilos arquiteturais](05-estilos-arquiteturais.md)

---

## O que é um padrão de projeto

Um **padrão de projeto** (design pattern) é uma solução testada para um problema
que aparece de novo e de novo. Não é código pronto pra copiar — é um **molde de
raciocínio**: "quando você tem o problema X, uma forma conhecida de resolver é Y".

Dois avisos de maturidade antes de começar:

1. **Padrão é vocabulário.** O maior valor é poder dizer "isso é um Strategy" e o
   time inteiro entender a estrutura na hora. Comunicação.
2. **Não saia aplicando padrões.** Padrão demais é tão ruim quanto de menos.
   Use quando o problema aparecer de verdade (lembra do YAGNI?). Reconhecer
   **quando NÃO usar** é sinal de senioridade.

Vou focar nos poucos padrões que você mais vai encontrar e entender — com o
problema que cada um resolve e um gancho no `aws-cost-monitor`.

---

## Strategy — trocar o "como" sem mudar o "quando"

**Problema:** você precisa fazer a mesma coisa de formas diferentes, escolhidas
em tempo de execução (ex.: gerar relatório em txt, json ou markdown).

**Solução:** encapsule cada forma ("estratégia") atrás de um contrato comum e
escolha qual usar.

**No projeto:** o `_BUILDERS` do `report_generator.py` é um Strategy em forma
simples. Cada builder é uma estratégia de formatação; `build_report_for_format`
escolhe a estratégia pelo nome do formato. Trocar/adicionar estratégia não mexe
nas outras.

```python
_BUILDERS = {"txt": build_report, "json": build_report_json, "markdown": build_report_markdown}
builder = _BUILDERS.get(fmt, build_report)   # escolhe a estratégia
return builder(*args, **kwargs)              # usa pela interface comum
```

> Em Python, muitas vezes um dicionário de funções já é um Strategy perfeitamente
> idiomático — você não precisa de classes e interfaces formais pra ter o padrão.

---

## Adapter — encaixar o que não encaixa

**Problema:** você quer usar algo que fala uma "língua" diferente da que o seu
sistema espera (uma API externa, uma lib de terceiro).

**Solução:** um **adaptador** traduz entre as duas línguas. Seu sistema fala com
o adaptador na SUA língua; o adaptador fala com o externo na língua dele.

**No projeto:** `cost_explorer.py` é um Adapter. Ele recebe a resposta crua da
AWS (uma estrutura complicada, cheia de `ResultsByTime`, `Groups`, `Metrics`) e
**traduz** pra uma lista simples de dicionários com `start`, `end`, `groups`. O
resto do sistema nunca vê a língua da AWS — só a sua.

> Benefício arquitetural: se a AWS mudar o formato, você conserta só o adaptador.
> O "mundo externo bagunçado" fica contido numa fronteira. (Custo de mudança
> baixo — módulo 01.)

---

## Factory — centralizar a criação

**Problema:** criar um objeto exige decidir qual tipo, com qual configuração, e
você não quer essa lógica espalhada por todo lado.

**Solução:** uma **fábrica** concentra a lógica de "como criar". Quem precisa do
objeto pede à fábrica e recebe pronto, sem saber dos detalhes.

**Gancho no projeto (futuro):** quando você criar a abstração `AIInterpreter`
(módulo 03), uma fábrica `make_interpreter(config)` leria a config e devolveria o
`LlamaInterpreter` ou o `OpenAIInterpreter` certo. O `main` pediria "me dá um
interpretador" sem saber qual é — a decisão fica num lugar só.

---

## Repository — esconder de onde vêm os dados

**Problema:** sua lógica de negócio não deveria precisar saber se os dados vêm de
um banco SQL, de um arquivo, de uma API ou da memória.

**Solução:** um **repositório** é um objeto que oferece métodos como `get`,
`save`, `list`, escondendo a fonte real. A lógica fala com o repositório; trocar
a fonte não afeta a lógica.

**Gancho no projeto (futuro):** a melhoria "persistência histórica"
(`../project-level-and-improvements.md`, item 3.2) pediria um `ReportRepository`
com `save(report)` e `list_recent()`. Começa salvando em arquivo; depois troca
pra SQLite sem o resto do sistema perceber. Esse é o padrão por trás de "trocar o
banco sem reescrever o sistema".

---

## Observer — avisar quem se interessa

**Problema:** quando algo acontece (um alerta de custo dispara), várias partes
podem querer reagir (logar, enviar e-mail, mandar pro Slack) — e você não quer
que a parte que detecta conheça todas as que reagem.

**Solução:** quem detecta **publica** um evento; os interessados se **inscrevem**
e reagem. O emissor não conhece os receptores.

**Gancho no projeto (futuro):** o "sistema de alertas" do roadmap. Quando
`generate_alerts` produz um alerta de severidade alta, ele publica um evento;
notificadores inscritos (e-mail, SNS) reagem. É também a base conceitual de
arquitetura **orientada a eventos** (módulo 05) e do serverless com EventBridge
(módulo 09).

---

## Um aviso sobre padrões (importante)

Você vai se empolgar e querer usar todos. Resista. O caminho saudável:

1. **Primeiro** escreva a solução simples que resolve (KISS).
2. **Quando** sentir a dor que o padrão resolve (duplicação, rigidez, acoplamento),
   aí refatore pro padrão.
3. **Nomeie** o padrão quando ele aparecer, pra comunicar.

Padrão aplicado antes da dor é complexidade especulativa. Padrão aplicado na dor
certa é elegância. A diferença é timing.

> Frase pra guardar: **"não procure onde aplicar um padrão; reconheça quando um
> padrão já quer nascer."**

---

## Prática do módulo

1. **Identifique os padrões escondidos.** No `aws-cost-monitor`, aponte onde
   estão o Strategy e o Adapter (já descritos acima) e **explique com suas
   palavras** o problema que cada um resolve ali. Escrever a explicação fixa o
   conceito.

2. **Projete um Repository no papel.** Desenhe a interface de um `ReportRepository`
   (quais métodos?) e descreva duas implementações: uma em arquivo, uma em SQLite.
   Qual parte do sistema mudaria ao trocar uma pela outra? (Resposta esperada:
   nenhuma, além da fábrica que escolhe.)

3. **Observer na vida real.** Pense num app que você usa e identifique um
   comportamento que parece Observer (algo acontece → várias coisas reagem).
   Descreva o evento e os "inscritos".

4. **Quando NÃO usar.** Dê um exemplo de um lugar no projeto onde adicionar um
   padrão (ex.: transformar as 3 regras de FinOps numa hierarquia de classes com
   Factory) seria **exagero**. Justifique com KISS/YAGNI.

---

> **Resumo:** padrões são soluções nomeadas pra problemas recorrentes — Strategy
> (trocar o como), Adapter (traduzir o externo), Factory (centralizar a criação),
> Repository (esconder a fonte de dados), Observer (avisar os interessados). Valem
> como vocabulário e como molde, mas só se aplicados quando a dor aparece.
>
> Próximo: **[05 — Camadas e estilos de arquitetura](05-estilos-arquiteturais.md)**.
