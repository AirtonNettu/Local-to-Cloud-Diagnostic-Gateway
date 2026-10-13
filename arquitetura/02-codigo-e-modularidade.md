# 02 — Pensar em código limpo e modular

> [⟵ Índice](README.md) · Anterior: [01](01-fundamentos.md) · Próximo: [03 — Princípios de design](03-principios-design.md)

---

## Por que começar pelo código

Arquitetura em grande escala é só modularidade em escala maior. Se você entende
por que separar duas funções, entende por que separar dois serviços — é o mesmo
princípio em tamanhos diferentes. Então a base da arquitetura começa aqui: **como
dividir código em peças que se encaixam bem.**

---

## Módulo: a unidade de organização

Um **módulo** é uma peça do sistema com uma responsabilidade clara: um arquivo,
uma classe, um pacote, mais tarde um serviço inteiro. Bons módulos têm duas
propriedades que andam juntas: **alta coesão** e **baixo acoplamento**.

### Coesão: as coisas que mudam juntas ficam juntas

**Coesão** é o quanto o que está dentro de um módulo pertence ali. Alta coesão =
tudo no módulo serve ao mesmo propósito.

- **Alta coesão (bom):** `cost_analyzer.py` só faz cálculo de custo. Tudo nele é
  sobre isso.
- **Baixa coesão (ruim):** um arquivo `utils.py` com uma função de data, uma de
  cálculo, uma que chama a AWS e uma que formata texto. Nada a ver entre si.

> Teste da coesão: "consigo descrever o que este módulo faz em uma frase, sem
> usar 'e'?" Se precisa de muitos "e", ele faz coisas demais.

### Acoplamento: o quanto um módulo depende de outro

**Acoplamento** é o quanto um módulo precisa conhecer das entranhas de outro.
Baixo acoplamento = os módulos conversam por contratos simples, sem conhecer os
detalhes internos um do outro.

- **Baixo acoplamento (bom):** `report_generator` recebe um dicionário pronto e
  formata. Ele não sabe de onde veio nem como foi calculado. Troque o cálculo
  inteiro: o gerador de relatório nem percebe.
- **Alto acoplamento (ruim):** se o gerador de relatório chamasse a AWS
  diretamente pra buscar um valor que faltou, ele passaria a depender da AWS,
  do formato da resposta, das credenciais... Mudar qualquer uma quebraria o
  relatório.

> A meta: **alta coesão dentro, baixo acoplamento fora.** Peças internamente
> focadas, fracamente ligadas entre si. É o segredo de sistemas que aceitam
> mudança.

---

## Responsabilidade única na prática

Cada módulo deve ter **uma razão para mudar**. Olhe como o `aws-cost-monitor`
divide o trabalho:

| Módulo | Única razão pra mudar |
|---|---|
| `cost_explorer.py` | Mudou a forma de buscar dados na AWS. |
| `cost_analyzer.py` | Mudou a forma de calcular. |
| `finops_rules.py` | Mudou uma regra de alerta. |
| `llama_client.py` | Mudou o provedor/forma de interpretação por IA. |
| `report_generator.py` | Mudou o formato/apresentação do relatório. |

Repare: se o negócio pede "adicionar formato CSV", você sabe EXATAMENTE onde
mexer (`report_generator`) e tem confiança de que não vai quebrar o cálculo. Isso
é responsabilidade única pagando dividendo.

**O cheiro de problema:** quando uma mudança simples te obriga a abrir cinco
arquivos, as responsabilidades estão mal divididas.

---

## Abstração: esconder o complicado atrás do simples

**Abstração** é expor o "o quê" e esconder o "como". Quando você chama
`get_costs()`, você não precisa saber que por dentro ela cria um cliente boto3,
monta um `TimePeriod`, trata quatro tipos de exceção e organiza a resposta. Você
só precisa do resultado. Todo esse "como" está **abstraído**.

Boas abstrações:
- têm um nome que diz o que fazem (`analyze_costs`, não `do_stuff`);
- escondem o que pode mudar (o detalhe interno) e expõem o que é estável (o
  contrato);
- reduzem o que você precisa guardar na cabeça pra usá-las.

> Abstração não é "deixar vago". É **esconder a complexidade certa**. Uma boa
> abstração você usa sem ler o código de dentro.

---

## Contratos: a fronteira entre módulos

O **contrato** de um módulo é a promessa que ele faz: o que recebe, o que
devolve, o que acontece quando dá errado. É o que o resto do mundo pode confiar.

No `cost_analyzer.py`, o contrato de `analyze_costs` é: "me dê uma lista de
períodos, eu te devolvo um dicionário com `total_cost`, `percentages`,
`largest_service`...". Quem usa a função confia nesse contrato e não precisa
olhar o corpo dela.

Por que isso importa pra arquitetura: **se os contratos são claros e estáveis,
você pode reescrever o interior de um módulo inteiro sem avisar ninguém.** Os
testes verificam o contrato; o resto do sistema depende só dele.

> Hoje, neste projeto, o contrato é um `dict` solto — funciona, mas é frágil (um
> erro de digitação na chave só aparece em runtime). No módulo 03 e 06 você verá
> como tornar contratos explícitos (type hints, dataclasses). Guarde a ideia.

---

## Dependências: quem conhece quem

Desenhe setas de "quem chama/usa quem". No `aws-cost-monitor`:

```
main → cost_explorer → (AWS)
main → cost_analyzer
main → finops_rules
main → llama_client → (Llama)
main → report_generator
```

Repare numa coisa importante: `cost_analyzer` **não** chama `cost_explorer`. Ele
só recebe os dados já coletados. Isso significa que o cálculo não depende da
coleta — você pode testar o cálculo com dados fabricados. Essa **direção das
dependências** é uma decisão arquitetural, e das boas.

> Regra que você vai aprofundar no módulo 03 (inversão de dependência): faça as
> dependências apontarem pra abstrações estáveis, não pra detalhes voláteis. O
> cálculo (estável, regra de negócio) não deve depender da coleta (detalhe, pode
> mudar de AWS pra outra nuvem).

---

## Nomes: a documentação que não mente

Código é lido muito mais vezes do que escrito. Nomes bons são a forma mais barata
de arquitetura legível.

- Nome diz a **intenção**: `has_positive_cost` é melhor que `flag`.
- Função é um **verbo** (`analyze_costs`, `save_report`); dado é um **substantivo**
  (`total_cost`, `alerts`).
- Evite abreviação que só você entende. `pct` passa; `tc_usd_fnl` não.

> Comentário desatualizado mente. Nome bem escolhido não — ele é o próprio código.

---

## Prática do módulo

1. **Caça à coesão.** Abra `src/reports/report_generator.py`. Liste tudo que ele
   faz. Ele tem uma responsabilidade só, ou está começando a fazer coisas demais
   (formatar texto, JSON, markdown E salvar arquivo)? Escreva sua opinião: isso é
   coesão aceitável ou já pediria uma separação? Não há resposta única — treine o
   argumento.

2. **Mapa de dependências.** Desenhe em papel as setas de quem-usa-quem do
   projeto. Marque com um círculo a dependência externa mais perigosa (a que mais
   pode mudar fora do seu controle). Dica: é a AWS. Por que o projeto a isolou num
   arquivo só?

3. **Quebre o contrato.** Em `cost_analyzer.py`, imagine que você renomeasse a
   chave `total_cost` para `total`. Quantos outros arquivos quebrariam? Use busca
   no editor por `total_cost` pra descobrir. Isso te mostra, na prática, o que é
   um contrato e por que mudá-lo é caro.

4. **Reescreva um nome.** Encontre no projeto uma variável de nome fraco (ou
   invente um exemplo ruim) e reescreva com um nome que revele intenção. Explique
   por que o novo é melhor.

---

> **Resumo:** módulos com alta coesão (focados) e baixo acoplamento (independentes),
> conectados por contratos claros, com dependências apontando na direção certa, e
> nomes que revelam intenção. Isso é arquitetura no tamanho "código" — e é a mesma
> ideia que escala pra sistemas inteiros.
>
> Próximo: **[03 — Princípios de design (SOLID e companhia)](03-principios-design.md)**.
