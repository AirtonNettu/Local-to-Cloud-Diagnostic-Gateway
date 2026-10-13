# 08 — Documentar e comunicar arquitetura

> [⟵ Índice](README.md) · Anterior: [07](07-qualidade-testes-observabilidade.md) · Próximo: [09 — Nuvem e soluções](09-nuvem-e-solucoes.md)

---

## A habilidade mais subestimada

Um arquiteto que não comunica não é arquiteto — é alguém com opiniões na cabeça.
A arquitetura só existe de verdade quando o **time inteiro a entende e a segue**.
Por isso, saber desenhar, escrever e defender decisões vale tanto quanto saber
tomá-las.

A boa notícia: comunicar arquitetura tem técnicas aprendíveis. Vamos às
principais.

---

## Diagramas: o mapa do sistema

Uma imagem economiza mil palavras — se for a imagem certa. O problema de muitos
diagramas é tentar mostrar tudo de uma vez e virar uma teia ilegível. A solução é
mostrar **um nível de detalhe por vez**.

### O modelo C4 (o mais útil pra começar)

C4 propõe quatro níveis de zoom, do mais distante ao mais próximo:

1. **Contexto:** o sistema como uma caixa só, cercado pelos usuários e sistemas
   externos com quem fala. Responde "o que é isso e com quem conversa?".
   - *No projeto:* `[Usuário] → [AWS Cost Monitor] → [AWS Cost Explorer]` e
     `→ [Servidor Llama]`.
2. **Contêineres:** as grandes partes executáveis (apps, bancos, serviços).
   - *No projeto:* a aplicação Python, o servidor Llama, (futuro) um banco.
3. **Componentes:** dentro de um contêiner, os módulos e como se relacionam.
   - *No projeto:* `cost_explorer`, `cost_analyzer`, `finops_rules`,
     `llama_client`, `report_generator` — exatamente o diagrama do `README.md`.
4. **Código:** classes/funções (raramente desenhado à mão; a IDE já mostra).

> A sacada do C4: cada diagrama tem **um público e um nível**. Você mostra o de
> Contexto pro gerente, o de Componentes pro desenvolvedor. Não misture níveis no
> mesmo desenho — é o erro nº 1.

### Regras de um bom diagrama

- **Poucas caixas.** Se tem mais de ~7-9, você está misturando níveis. Agrupe.
- **Setas com significado.** Diga o que a seta representa ("envia custos",
  "consulta"). Seta sem rótulo é adivinhação.
- **Legenda.** Cores e formas devem significar algo explícito (o `README.md` do
  projeto faz isso: azul = cálculo, roxo tracejado = IA opcional).
- **Honesto, não aspiracional.** Desenhe o que É, não o que você gostaria que
  fosse. Diagrama que mente é pior que nenhum.

---

## ADR — Architecture Decision Record

Esta é, talvez, a ferramenta mais valiosa deste módulo inteiro.

**O problema:** seis meses depois, ninguém lembra *por que* decidiram usar X em
vez de Y. A pessoa nova chega, acha a decisão estranha, "conserta" — e reintroduz
o problema que a decisão original evitava.

**A solução:** um **ADR** é um registro curto de uma decisão arquitetural
importante e do porquê dela. Um arquivo pequeno por decisão. Formato clássico:

```markdown
# ADR 001 — Separar cálculo de interpretação por IA

## Status
Aceito

## Contexto
Precisamos interpretar custos em linguagem natural. LLMs podem "alucinar"
números, o que é inaceitável para dados financeiros.

## Decisão
Python faz todo o cálculo (determinístico, testável). A IA recebe apenas os
números já calculados e os interpreta, nunca os produz.

## Consequências
+ Valores sempre corretos e auditáveis.
+ A IA pode cair ou ser trocada sem afetar os números.
- O prompt precisa ser construído com os dados já formatados (passo extra).
```

Repare: o `aws-cost-monitor` **tem** essa decisão (a regra "Python calcula, IA
interpreta"), mas ela está espalhada em docstrings. Um ADR a tornaria oficial,
rastreável e defensável. (Boa ideia de melhoria: criar `docs/adr/` no projeto.)

> ADRs são imutáveis: você não apaga um, você escreve um novo que o **substitui**
> ("supersede"). Assim o histórico de raciocínio fica preservado — ouro puro pra
> quem chega depois, inclusive você mesmo no futuro.

---

## Escrever para ser entendido

Alguns hábitos de escrita técnica que fazem diferença:

- **Comece pela conclusão.** Diga a decisão/resposta primeiro, os detalhes depois.
  Quem lê decide se precisa se aprofundar.
- **Uma ideia por parágrafo.** Facilita achar e reler.
- **Concreto > abstrato.** "Reduz o custo de trocar de provedor de IA" é melhor
  que "aumenta a flexibilidade".
- **Mostre o trade-off.** Toda decisão tem um custo. Escondê-lo tira sua
  credibilidade; mostrá-lo constrói confiança.

> A documentação deste próprio projeto (os `docs/`) é um exemplo: deriva do código
> real, mostra decisões e até registra observações não corrigidas. Estude o estilo.

---

## Defender uma decisão (sem brigar)

Em algum momento você vai propor uma arquitetura e alguém vai discordar. Como
conduzir:

1. **Apresente o problema antes da solução.** Alinhe no "qual dor estamos
   resolvendo?" antes de defender o "como".
2. **Fale em trade-offs, não em certezas.** "Escolhi X porque prioriza
   manutenibilidade, aceitando um pouco mais de código" convence mais que "X é o
   certo".
3. **Separe fato de opinião.** "Isto é medido" vs "isto é meu julgamento". Seja
   honesto sobre qual é qual.
4. **Esteja pronto pra mudar de ideia.** O melhor argumento vence, não o maior
   cargo. Mudar de opinião com um bom dado é força, não fraqueza.
5. **Registre o resultado num ADR.** A discussão vira decisão documentada.

> Arquitetura é tanto técnica quanto social. A melhor solução que ninguém adota
> perde pra solução ok que o time abraça. Comunicação é o que fecha essa conta.

---

## Prática do módulo

1. **Desenhe os quatro níveis C4.** Pro `aws-cost-monitor`, esboce (papel serve) o
   diagrama de Contexto e o de Componentes. Note como o segundo é basicamente o
   diagrama do `README.md` — você já tinha um C4 e não sabia.

2. **Escreva um ADR de verdade.** Pegue uma decisão real do projeto — "relatórios
   são salvos como arquivos em `reports/`" ou "a camada de IA é opcional e
   não-bloqueante" — e escreva o ADR completo (Contexto, Decisão, Consequências).
   Guarde num `decisoes.md` ou proponha um `docs/adr/`.

3. **Defenda os dois lados.** Escreva dois parágrafos: um defendendo salvar
   relatórios em banco, outro defendendo manter em arquivo. Depois decida e
   justifique. Treina argumentar em trade-offs.

4. **Critique um diagrama.** Olhe o diagrama Mermaid do `README.md` com as regras
   deste módulo. Ele segue as boas práticas (poucas caixas, setas com sentido,
   legenda, honesto)? O que você melhoraria?

---

> **Resumo:** arquitetura só existe quando é comunicada. Diagramas C4 mostram um
> nível de zoom por vez; bons diagramas têm poucas caixas, setas com significado e
> são honestos. ADRs registram decisões e seus porquês, preservando o raciocínio
> no tempo. Escrever claro e defender em trade-offs (não em certezas) é metade do
> trabalho — a metade social.
>
> Próximo: **[09 — Fundamentos de nuvem e arquiteto de soluções](09-nuvem-e-solucoes.md)**.
