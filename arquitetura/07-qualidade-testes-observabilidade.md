# 07 — Qualidade: testes, erros, observabilidade

> [⟵ Índice](README.md) · Anterior: [06](06-dados-apis-integracao.md) · Próximo: [08 — Documentar e comunicar](08-documentar-e-comunicar.md)

---

## Qualidade é arquitetura, não acabamento

Iniciante trata teste e tratamento de erro como "a parte chata do fim". Arquiteto
sabe que são **propriedades estruturais**: um sistema testável e observável é um
sistema bem arquitetado, e um que não é, não é. Qualidade se projeta desde o
começo.

---

## Testes: a rede de segurança que permite mudar

O valor real do teste não é "provar que funciona hoje". É **permitir mudar amanhã
sem medo**. Com testes, você refatora, atualiza, melhora — e eles gritam se você
quebrou algo. Sem testes, cada mudança é uma aposta.

> Reveja o `../../IMPLEMENTAR.md`: você mudou o `cost_analyzer`, rodou os testes,
> e eles confirmaram que o comportamento se manteve. Essa confiança é o produto.

### A pirâmide de testes

```
        /\        Poucos    E2E (ponta a ponta: o sistema inteiro)
       /  \
      /    \      Alguns    Integração (módulos juntos, com DB/API)
     /------\
    /        \    Muitos    Unitários (uma função/módulo isolado)
   /----------\
```

- **Unitários (base, muitos):** testam uma peça isolada, rápidos, sem rede. São a
  maioria dos testes do `aws-cost-monitor` — testam o cálculo com dados
  fabricados.
- **Integração (meio, alguns):** testam peças trabalhando juntas (ex.: coleta +
  análise), muitas vezes com dependências reais ou simuladas.
- **E2E (topo, poucos):** testam o fluxo completo como um usuário faria. Valiosos,
  mas lentos e frágeis — por isso poucos.

> A forma de pirâmide é a receita: **muitos** testes rápidos e baratos na base,
> **poucos** lentos e caros no topo. Invertida (muitos E2E, poucos unitários) é
> um antipadrão: suíte lenta e instável.

### Mocks: isolar o que você não controla

Um **mock** é um dublê — um objeto falso que finge ser uma dependência externa.
Os testes do projeto usam mocks pra não chamar a AWS nem o Llama de verdade.

Por que isso é arquitetura e não truque: **você só consegue "mockar" o que está
desacoplado.** O cálculo é testável sem rede *porque* não depende diretamente da
coleta. Se fosse tudo grudado, não daria pra isolar. **Código testável = código
bem desenhado.** As duas coisas são a mesma vista de ângulos diferentes.

### TDD em uma linha

**Test-Driven Development:** escreva o teste primeiro (ele falha → "vermelho"),
faça passar (→ "verde"), melhore (refatore). Você praticou isso no
`../../IMPLEMENTAR.md` ao criar a regra `_check_drop`. TDD força você a definir "o
que é certo" antes de codar — e isso melhora o design, não só a cobertura.

---

## Tratamento de erros: falhar bem é uma arte

Sistemas falham. A pergunta não é "se", é "como eu falho". Falhar **bem** significa:

### 1. Falhe de forma explícita, não silenciosa

O pior erro é o que ninguém vê. Nunca engula uma exceção com um `except:` vazio.
O `aws-cost-monitor` converte erros de baixo nível em exceções de domínio
(`CostExplorerError`, `LlamaUnavailableError`) com mensagens que dizem o que
fazer. O erro vira informação útil, não mistério.

### 2. Preserve a causa raiz

Repare no `raise ... from exc` do `cost_explorer.py`. Isso mantém a exceção
original encadeada à nova. Quando você for depurar, a trilha completa está lá — a
mensagem amigável no topo, a causa técnica embaixo.

### 3. Decida o significado da falha

Nem toda falha é igual. O `main.py` decide:
- `CostExplorerError` → encerra com código `1` (não dá pra continuar sem dados).
- Sem dados → código `0` com aviso (não é erro, só não há o que mostrar).
- IA indisponível → segue sem ela (falha tolerável).

O **código de saída** e o **tipo de exceção** comunicam intenção. Isso é desenho,
não acaso.

### 4. Falhe no nível certo

Capture o erro onde você pode fazer algo útil com ele. Capturar cedo demais
esconde; tarde demais, o programa já quebrou. O padrão do projeto — a camada baixa
levanta a exceção específica, o orquestrador decide o que fazer — é o nível certo.

---

## Observabilidade: enxergar o sistema vivo

Em produção, você não tem o debugger aberto. Precisa **enxergar de fora** o que o
sistema está fazendo. Observabilidade tem três pilares:

| Pilar | O que responde | Exemplo |
|---|---|---|
| **Logs** | "O que aconteceu, em ordem?" | "Coleta iniciada", "IA indisponível" |
| **Métricas** | "Quanto / com que frequência?" | tempo de execução, nº de alertas |
| **Traces** | "Por onde passou a requisição?" | o caminho de uma chamada entre serviços |

### Logging > print

O `aws-cost-monitor` hoje usa `print` (uma das melhorias apontadas é trocar por
`logging`). A diferença é arquitetural:

- `print` sempre sai, sem nível, sem contexto, sem como desligar.
- `logging` tem **níveis** (DEBUG/INFO/WARNING/ERROR), **formato** padronizado, e
  você controla **para onde** vai (console, arquivo, serviço) sem mudar o código
  que loga.

> Regra: log o suficiente pra entender o que aconteceu sem reproduzir o problema,
> e **nunca** logue segredo (credencial, dado sensível). O projeto já cuida de não
> expor credenciais — mantenha isso no logging.

---

## Qualidade automatizada: CI, linter, cobertura

Fechando o ciclo (e conectando com o `../ci-and-env-explained.md`):

- **CI (integração contínua):** roda os testes a cada mudança, automaticamente.
  Garante que a rede de segurança é sempre acionada, não só quando você lembra.
- **Linter** (ex.: `ruff`): verifica estilo e erros comuns sem rodar o código.
- **Cobertura** (ex.: `pytest-cov`): mede quanto do código os testes exercitam.
  Útil como bússola — mas 100% de cobertura não garante ausência de bugs. Cobrir
  os **caminhos que importam** (como os casos de borda do projeto) vale mais que
  um número alto.

---

## Prática do módulo

1. **Classifique os testes do projeto.** Abra a pasta `tests/`. Os testes são
   majoritariamente unitários, de integração ou E2E? Isso bate com a pirâmide?
   Escreva sua conclusão.

2. **Projete um teste de integração.** Os testes atuais isolam cada módulo.
   Descreva (não precisa codar) um teste de integração que verifique coleta +
   análise + geração de relatório juntas, usando um mock só pra AWS. O que ele
   provaria que os unitários não provam?

3. **Mapeie as decisões de falha.** Liste os três caminhos de erro do `main.py`
   (visto acima) e, pra cada um, explique por que o código de saída escolhido faz
   sentido pra quem roda o programa (ou um agendador que depende dele).

4. **Planeje o logging.** Escolha três pontos do fluxo onde um log seria valioso
   em produção e, pra cada um, diga o nível (INFO/WARNING/ERROR) e o que a
   mensagem diria — sem vazar segredo.

---

> **Resumo:** testes são a rede que permite mudar sem medo (pirâmide: muitos
> unitários, poucos E2E; mocks exigem desacoplamento). Falhar bem é explícito,
> preserva a causa, decide o significado e acontece no nível certo.
> Observabilidade (logs, métricas, traces) é enxergar o sistema vivo. CI/linter/
> cobertura automatizam a garantia. Tudo isso é estrutura, não acabamento.
>
> Próximo: **[08 — Documentar e comunicar arquitetura](08-documentar-e-comunicar.md)**.
