# 06 — Dados, APIs e integração

> [⟵ Índice](README.md) · Anterior: [05](05-estilos-arquiteturais.md) · Próximo: [07 — Qualidade, testes, observabilidade](07-qualidade-testes-observabilidade.md)

---

## Por que dados e integração são território do arquiteto

Sistemas raramente vivem sozinhos. Eles guardam dados e conversam com outros
sistemas. **Como** os dados são modelados e **como** as integrações são feitas são
decisões caras de mudar (lembra do módulo 01) — logo, arquitetura pura.

---

## Modelagem de dados: o contrato mais duradouro

O formato dos seus dados sobrevive a quase tudo. Você reescreve código à vontade,
mas mudar a estrutura de dados que já tem milhões de registros é das coisas mais
caras que existem. Por isso, pense bem no modelo.

### Dados explícitos vencem dados implícitos

No `aws-cost-monitor`, os dados hoje trafegam como `dict` solto:

```python
analysis = {"total_cost": 50.0, "percentages": {...}, "largest_service": "EC2"}
```

Funciona, mas o contrato é **implícito** — está só na cabeça de quem escreveu e
nas docstrings. Um erro de digitação (`analysis["persentages"]`) só explode em
runtime.

Tornar explícito (uma melhoria real do projeto):

```python
from dataclasses import dataclass

@dataclass
class CostAnalysis:
    services: dict[str, float]
    total_cost: float
    positive_services: dict[str, float]
    percentages: dict[str, float]
    largest_service: str | None
    has_positive_cost: bool
```

Agora o contrato é **código**: a IDE autocompleta, o checker pega o erro de
digitação, e a estrutura está documentada num lugar só. Esse salto —
de dado implícito pra explícito — é um marco de maturidade.

### Normalização vs desnormalização (noção)

- **Normalizar:** cada informação mora num lugar só, sem repetição. Bom pra
  consistência (muda num lugar, vale pra todos).
- **Desnormalizar:** repetir dado de propósito pra ler mais rápido. Bom pra
  desempenho de leitura, ao custo de ter que atualizar em vários lugares.

É o mesmo trade-off DRY do código, agora nos dados. Bancos relacionais (SQL)
tendem a normalizar; muitos bancos NoSQL desnormalizam pra escalar leitura.

---

## APIs: a fronteira entre sistemas

Uma **API** (Application Programming Interface) é o contrato pelo qual um sistema
oferece seus serviços a outro. É uma fronteira — e fronteiras bem desenhadas são
o que permite sistemas evoluírem sem quebrar uns aos outros.

### REST em cinco minutos

**REST** é o estilo mais comum de API web. A ideia central: você expõe **recursos**
(coisas: um usuário, um relatório) identificados por URLs, e age sobre eles com os
**verbos HTTP**:

| Verbo | Significado | Exemplo |
|---|---|---|
| GET | ler, sem efeito colateral | `GET /reports/42` |
| POST | criar | `POST /reports` |
| PUT/PATCH | atualizar | `PATCH /reports/42` |
| DELETE | remover | `DELETE /reports/42` |

Boas práticas que denunciam quem entende:
- **Substantivos nos recursos, verbos no método.** `GET /reports`, não
  `GET /getReports`.
- **Códigos de status honestos:** 200 ok, 201 criado, 400 erro do cliente, 404
  não achou, 500 erro do servidor. (O `cost_explorer.py` já pensa assim ao
  traduzir erros da AWS — mesma mentalidade.)
- **Sem estado (stateless):** cada requisição carrega o que precisa; o servidor
  não "lembra" da anterior. Isso é o que permite escalar horizontalmente.

> O `aws-cost-monitor` **consome** uma API (a da AWS, via boto3) e, no formato
> JSON do relatório, já se prepara pra um dia **expor** uma. O JSON estruturado é
> um contrato pensado pra integração — exatamente o que uma API serviria.

---

## Síncrono vs assíncrono

Duas formas de dois sistemas conversarem:

- **Síncrono:** peço e **espero** a resposta (uma chamada HTTP comum). Simples,
  direto, mas eu fico bloqueado e dependente do outro estar no ar.
- **Assíncrono:** mando uma mensagem/evento e **sigo minha vida**; o outro
  processa quando puder (filas, eventos). Mais resiliente e escalável, porém mais
  complexo de raciocinar.

**No projeto:** a chamada ao Llama é síncrona (manda o prompt, espera o texto). Já
o futuro "sistema de alertas" serverless seria assíncrono (evento → notificação).
Escolher entre os dois é decisão arquitetural: acoplamento no tempo vs
simplicidade.

---

## Resiliência em integrações

Todo sistema externo **vai** falhar uma hora. Arquiteto assume isso e se protege:

- **Timeout:** nunca espere pra sempre. O `llama_client.py` usa `LLAMA_TIMEOUT` —
  se o Llama não responder a tempo, falha de forma controlada.
- **Tratar a falha explicitamente:** o projeto converte falhas em
  `LlamaUnavailableError` e `CostExplorerError`, com mensagem clara. Nada de
  engolir erro.
- **Degradação graciosa:** se a IA cai, o relatório sai sem ela. O sistema fica
  **parcialmente** útil em vez de totalmente quebrado.
- **Retry com cautela** (conceito pra frente): tentar de novo pode ajudar em
  falhas passageiras, mas retry mal feito vira tempestade. Use com backoff
  (espera crescente) e limite.

> Esses quatro hábitos são o que separa "funciona na minha máquina" de "aguenta o
> mundo real". O `aws-cost-monitor` já pratica os três primeiros — estude-os como
> modelo.

---

## Versionamento: evoluir sem quebrar quem depende de você

Quando outros dependem da sua API ou do seu formato de dados, você não pode mudar
o contrato do dia pra noite. Soluções:

- **Versão na API:** `/v1/reports`, `/v2/reports` convivem; clientes migram no
  tempo deles.
- **Mudanças retrocompatíveis:** adicionar um campo novo é seguro; remover ou
  renomear um existente quebra. Adicione, não remova.
- **Semantic Versioning** (como no `CHANGELOG.md` do projeto): `MAJOR.MINOR.PATCH`
  — o MAJOR sobe quando você quebra compatibilidade. É um contrato com quem usa.

---

## Prática do módulo

1. **Modele com dataclass.** Pegue a saída de `compare_periods` (`previous_total`,
   `current_total`, `variation`) e escreva a `dataclass` correspondente. Qual tipo
   tem `variation`? (Cuidado: pode ser `None`.) Isso treina pensar em contrato
   explícito.

2. **Desenhe a API.** Se o `aws-cost-monitor` virasse um serviço web, desenhe 3
   endpoints REST (verbo + URL + o que retorna). Ex.: `GET /reports` lista
   relatórios. Pense nos códigos de status de sucesso e erro.

3. **Síncrono ou assíncrono?** Pra cada caso, escolha e justifique: (a) gerar o
   relatório sob demanda quando o usuário clica; (b) enviar uma notificação
   quando um alerta de custo dispara às 3h da manhã. Perceba por que as respostas
   diferem.

4. **Caça à resiliência.** Encontre no `llama_client.py` as linhas que
   implementam timeout e tratamento de falha. Explique o que aconteceria SEM cada
   uma delas.

---

> **Resumo:** o modelo de dados é o contrato mais duradouro — torne-o explícito.
> APIs REST expõem recursos por verbos HTTP e devem ser stateless e honestas nos
> status. Integrações falham: proteja-se com timeout, tratamento explícito e
> degradação graciosa. Evolua contratos sem quebrar quem depende, via
> versionamento.
>
> Próximo: **[07 — Qualidade: testes, erros, observabilidade](07-qualidade-testes-observabilidade.md)**.
