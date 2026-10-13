# 03 — Princípios de design (SOLID e companhia)

> [⟵ Índice](README.md) · Anterior: [02](02-codigo-e-modularidade.md) · Próximo: [04 — Padrões de projeto](04-padroes-de-projeto.md)

---

## Antes do SOLID: não decore, sinta a dor

Princípios de design são **cicatrizes de dores reais**. Cada um existe porque
alguém sofreu com a ausência dele. Se você decorar as siglas sem sentir a dor,
vira papagaio. Então, pra cada princípio, vou primeiro mostrar a **dor**, depois
o **remédio**.

---

## SOLID — cinco princípios, uma letra cada

### S — Single Responsibility (Responsabilidade Única)

**Dor:** um arquivo que faz tudo. Toda mudança nele arrisca quebrar coisas sem
relação. Dois motivos diferentes forçam a mexer no mesmo lugar.

**Remédio:** cada módulo tem **uma razão pra mudar**. (Visto no módulo 02.)

**No projeto:** `cost_analyzer` muda só se o cálculo muda; `report_generator`
muda só se a apresentação muda. São razões independentes, logo arquivos
independentes.

### O — Open/Closed (Aberto/Fechado)

**Dor:** pra adicionar um caso novo, você edita um `if/elif` gigante que já
funciona — e corre o risco de quebrar os casos antigos.

**Remédio:** o código deve ser **aberto pra extensão, fechado pra modificação**.
Você adiciona comportamento novo sem reabrir o que já funciona.

**No projeto:** olhe o `_BUILDERS` em `report_generator.py` — um dicionário que
mapeia formato → função. Pra adicionar CSV, você **adiciona** uma entrada e uma
função; não reescreve as existentes. Isso é Open/Closed na prática.

```python
_BUILDERS = {"txt": build_report, "json": build_report_json, "markdown": build_report_markdown}
# Adicionar "csv": build_report_csv — sem tocar nos outros.
```

### L — Liskov Substitution (Substituição de Liskov)

**Dor:** você tem uma "família" de coisas que deveriam ser intercambiáveis, mas
uma delas se comporta diferente e quebra quem a usa.

**Remédio:** se B é um tipo de A, usar B no lugar de A **não pode** surpreender.
Um subtipo honra o contrato do tipo base.

**Exemplo mental:** se você tem uma interface `AIInterpreter` com `interpret() ->
str`, qualquer implementação (Llama, OpenAI) deve devolver uma string de verdade,
não lançar um erro inesperado ou devolver `None`. Quem usa a interface confia no
contrato, independentemente da implementação.

### I — Interface Segregation (Segregação de Interface)

**Dor:** uma interface gorda obriga quem a implementa a fornecer métodos que não
usa.

**Remédio:** **muitas interfaces pequenas e específicas** são melhores que uma
grande. Cada cliente depende só do que precisa.

**Exemplo:** um `AIInterpreter` só precisa de `interpret(...)`. Não force nele um
`train()` ou `list_models()` que só um provedor tem. Mantenha a interface mínima.

### D — Dependency Inversion (Inversão de Dependência)

**Dor:** sua regra de negócio importante depende diretamente de um detalhe que
muda (um fornecedor específico, um banco específico). Trocar o detalhe exige
reescrever a regra.

**Remédio:** dependa de **abstrações**, não de implementações concretas. O
detalhe é que se encaixa na abstração, não o contrário.

**No projeto, hoje e amanhã:**
- *Hoje:* `main.py` importa `interpret` direto do `llama_client`. Funciona, mas
  está acoplado ao Llama.
- *Amanhã (melhoria):* defina uma abstração `AIInterpreter`. O `main` passa a
  depender dela. `LlamaInterpreter` e um futuro `OpenAIInterpreter` a implementam.
  Agora trocar de IA é escolher qual implementação injetar — sem tocar no `main`.

```python
from typing import Protocol

class AIInterpreter(Protocol):
    def interpret(self, analysis, comparison, alerts=None) -> str: ...

# main depende de AIInterpreter (abstração), não de LlamaInterpreter (detalhe).
def run(interpreter: AIInterpreter): ...
```

> Essa é a inversão: a seta de dependência, que apontava pro detalhe (Llama),
> passa a apontar pra abstração (a interface). O detalhe fica substituível.

---

## Os princípios "de bolso": DRY, KISS, YAGNI

### DRY — Don't Repeat Yourself

Cada pedaço de conhecimento mora num lugar só. Se a regra "custo positivo é
> 0" aparece em três arquivos e um dia vira ">= 0", você quer mudar em UM lugar.

**Cuidado com o exagero:** DRY é sobre **conhecimento duplicado**, não sobre
código parecido por acaso. Duas funções com duas linhas iguais mas propósitos
diferentes NÃO precisam virar uma. Juntar coisas que só parecem iguais cria
acoplamento ruim.

### KISS — Keep It Simple

A solução mais simples que resolve o problema vence. Complexidade só se paga
quando o problema realmente exige. O `aws-cost-monitor` podia ter um framework
de plugins pra regras de FinOps — mas três funções simples resolvem, então três
funções é o certo.

### YAGNI — You Aren't Gonna Need It

Não construa pro futuro imaginário. "E se um dia precisarmos de 10 provedores de
IA?" Talvez nunca precise. Construa pro que o problema pede HOJE, mantendo o
código aberto pra extensão (Open/Closed) — assim, se o futuro chegar, você
estende sem ter desperdiçado esforço antes da hora.

> KISS e YAGNI puxam pra simplicidade; Open/Closed e Dependency Inversion puxam
> pra flexibilidade. A arte do arquiteto é o **equilíbrio**: simples agora,
> flexível onde a mudança é provável. Flexibilidade onde a mudança é improvável é
> só complexidade desperdiçada.

---

## Composição vs herança

Duas formas de reaproveitar comportamento:

- **Herança** ("é um"): um `RelatorioPDF` é um `Relatorio`. Poderoso, mas cria
  acoplamento forte — o filho fica preso à estrutura do pai.
- **Composição** ("tem um" / "usa um"): um `Relatorio` *tem um* formatador.
  Monta-se o comportamento juntando peças.

**Conselho prático moderno:** **prefira composição a herança.** Ela é mais
flexível e evita hierarquias rígidas. O `aws-cost-monitor` usa composição o tempo
todo: o `main` *compõe* o fluxo juntando coleta + análise + regras + IA +
relatório, em vez de criar uma super-classe que faz tudo.

---

## Guard clauses: um padrão de clareza

Repare neste padrão, que se repete em `finops_rules.py`:

```python
def _check_growth(comparison, threshold):
    if comparison is None:
        return None
    variation = comparison.get("variation")
    if variation is None:
        return None
    # ... só chega aqui quando os dados são válidos
```

São **guard clauses**: tratar os casos de saída logo no começo e sair cedo, em
vez de aninhar tudo em `if` dentro de `if`. O resultado é código "plano", fácil
de ler de cima a baixo. É um hábito pequeno com grande efeito na clareza.

---

## Prática do módulo

1. **Caça ao Open/Closed.** Encontre no projeto outro lugar, além do `_BUILDERS`,
   onde adicionar um caso novo não exige reescrever os antigos. (Dica: o
   `_FORMAT_EXTENSIONS`.) Explique como ele cumpre o princípio.

2. **Projete a inversão de dependência.** Sem codar ainda, só desenhe: como ficaria
   o fluxo se existisse `AIInterpreter`? Quem dependeria de quem? Desenhe as setas
   antes e depois da inversão. Essa é a melhoria 2.2 do
   `../project-level-and-improvements.md` — você está projetando ela.

3. **Pegue um DRY falso.** Pense em duas funções que têm código parecido mas
   propósitos diferentes. Argumente por que juntá-las seria um erro, mesmo
   "removendo duplicação".

4. **KISS na vida real.** Descreva uma funcionalidade que você teve vontade de
   adicionar ao projeto "pra ficar mais completo". Pergunte-se: o problema atual
   pede isso? Se não, você acabou de aplicar YAGNI.

---

> **Resumo:** SOLID são cinco remédios pra cinco dores de código rígido. DRY/KISS/
> YAGNI mantêm você honesto entre simplicidade e flexibilidade. Composição sobre
> herança dá flexibilidade sem rigidez. Nada disso é regra sagrada — são
> ferramentas pra reduzir custo de mudança, que é o objetivo do módulo 01.
>
> Próximo: **[04 — Padrões de projeto que importam](04-padroes-de-projeto.md)**.
