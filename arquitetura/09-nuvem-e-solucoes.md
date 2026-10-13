# 09 — Fundamentos de nuvem e arquiteto de soluções

> [⟵ Índice](README.md) · Anterior: [08](08-documentar-e-comunicar.md) · Próximo: [10 — Projeto final e carreira](10-projeto-final-e-carreira.md)

---

## Onde o arquiteto de software vira arquiteto de soluções

Até aqui a trilha olhou **pra dentro** de um sistema. O **Arquiteto de Soluções**
(AS) dá mais um zoom out: olha **como vários sistemas e serviços** — quase sempre
na nuvem — se combinam pra resolver uma necessidade de **negócio**, equilibrando
custo, segurança, escala e prazo.

O AS fala duas línguas: a técnica (como no resto da trilha) e a de negócio (quanto
custa, que risco corre, quando entrega, que valor gera). Este módulo te dá a base
da parte de nuvem; a parte de negócio você afia com experiência.

> O `aws-cost-monitor` é, por acaso, uma ferramenta de **FinOps** — a disciplina
> de gestão de custo na nuvem. Então você já está estudando um pedaço do mundo do
> AS sem ter percebido. (Veja o `../study-guide.md`.)

---

## O que é "nuvem", de verdade

Nuvem é usar computação de outra pessoa (AWS, Azure, GCP) sob demanda, pagando
pelo que usar, em vez de comprar e manter servidores próprios. O ganho não é só
custo — é **elasticidade** (crescer e encolher conforme a necessidade) e
**velocidade** (subir um recurso em segundos).

### Os modelos de serviço (quanto a nuvem gerencia por você)

| Modelo | A nuvem cuida de... | Você cuida de... | Analogia |
|---|---|---|---|
| **IaaS** | hardware, rede | SO, runtime, app | aluga o terreno |
| **PaaS** | + SO, runtime | só o app | aluga a casa mobiliada |
| **FaaS/Serverless** | + escala, servidor | só a função | paga por hóspede |
| **SaaS** | tudo | só usar | hotel |

Quanto mais pra baixo, menos você opera e mais foca no que gera valor — ao custo
de menos controle. Escolher o modelo certo pra cada peça é decisão de AS.

### Modelo de responsabilidade compartilhada

Ponto crítico de segurança: na nuvem, a segurança é **dividida**. O provedor
protege a nuvem (hardware, data center); **você** protege o que coloca nela
(seus dados, suas permissões, suas senhas). Achar que "a AWS cuida de tudo" é a
origem de muitos vazamentos. O `aws-cost-monitor` já pratica a sua parte: IAM com
menor privilégio, nenhuma credencial no código.

---

## Os pilares de uma boa arquitetura de nuvem

Os grandes provedores publicam "frameworks de boa arquitetura" (a AWS chama de
Well-Architected). Os pilares, em linguagem simples:

1. **Excelência operacional:** consigo operar, monitorar e melhorar isso no dia a
   dia? (Liga com observabilidade, módulo 07.)
2. **Segurança:** dados protegidos, acesso mínimo necessário, tudo auditável.
3. **Confiabilidade:** aguenta falha e se recupera? Tem plano pra quando cair?
4. **Eficiência de desempenho:** usa o recurso certo pro trabalho, sem desperdício.
5. **Otimização de custo:** pago só pelo que preciso? **(É literalmente o que o
   `aws-cost-monitor` ajuda a enxergar — FinOps.)**
6. **Sustentabilidade:** uso consciente de recursos.

> O AS usa esses pilares como **checklist de revisão**: diante de uma proposta,
> pergunta "e quanto à segurança? e ao custo? e se falhar?". É a versão nuvem das
> três perguntas do módulo 01.

---

## Serviços que você vai encontrar sempre (vocabulário mínimo)

Sem decorar catálogo — só os tipos de peça que todo desenho de solução usa:

- **Computação:** onde o código roda. Pode ser servidor (VM), contêiner, ou
  **função serverless** (ex.: AWS Lambda — roda seu código sob um evento, sem
  servidor pra gerir).
- **Armazenamento:** objetos/arquivos (ex.: S3), ou disco.
- **Banco de dados:** relacional (SQL) ou NoSQL, gerenciado pela nuvem.
- **Mensageria/eventos:** filas e barramentos de eventos (ex.: SNS, EventBridge)
  que conectam partes de forma assíncrona (módulos 05 e 06).
- **Rede e identidade:** quem acessa o quê (IAM), e como as peças se enxergam.
- **Observabilidade:** logs e métricas gerenciados (ex.: CloudWatch).

Com esses tipos de peça, você monta quase qualquer solução. O trabalho do AS é
**escolher e conectar** as peças certas pro problema e pro orçamento.

---

## Estudo de caso: o `aws-cost-monitor` como solução serverless

O roadmap do projeto prevê virar serverless. Vamos desenhar isso como um AS faria
— é a síntese de tudo que você aprendeu.

**Necessidade de negócio:** monitorar custos automaticamente e avisar quando algo
foge do normal, sem ninguém rodar nada à mão.

**Desenho da solução:**

```
[EventBridge: agenda diária]
          ↓ (evento "está na hora")
   [Lambda: roda o monitor]
          ↓ consulta
   [AWS Cost Explorer] → cálculo + regras de FinOps (o código atual!)
          ↓ gera
   [Relatório JSON] → salva em [S3]
          ↓ se houver alerta de severidade alta
   [SNS] → e-mail / Slack para o time
          ↓ tudo registrado em
   [CloudWatch: logs e métricas]
```

**Por que cada escolha (o raciocínio do AS):**
- **Lambda** em vez de servidor ligado 24h: o monitor roda minutos por dia. Pagar
  por servidor parado seria desperdício — fere o pilar de custo. Serverless paga
  só pela execução. (E, ironicamente, é FinOps aplicado à própria ferramenta.)
- **EventBridge** pra agendar: desacopla "quando rodar" de "o que rodar"
  (event-driven, módulo 05). Mudar o horário não toca no código.
- **SNS** pra alertas: assíncrono (módulo 06), e novos canais de notificação
  entram sem mexer em quem detecta (Observer, módulo 04).
- **S3** pros relatórios: barato, durável, resolve a "persistência histórica".
- **CloudWatch:** observabilidade (módulo 07) sem montar infra própria.
- **IAM mínimo:** o Lambda recebe só `ce:GetCostAndUsage` e o necessário —
  responsabilidade compartilhada, segurança.

**O que já está pronto pra isso:** o código determinístico do projeto roda
igualzinho dentro de um Lambda. O relatório JSON foi pensado pra integração. As
boas decisões arquiteturais que você estudou são o que tornam essa evolução
**barata** — custo de mudança baixo (módulo 01). Isso não é sorte; é projeto.

---

## Prática do módulo

1. **Classifique por modelo de serviço.** Pro desenho serverless acima, diga qual
   modelo (IaaS/PaaS/FaaS/SaaS) é cada peça. Qual dá menos trabalho operacional? E
   menos controle?

2. **Aplique os pilares.** Pegue o desenho e revise-o pelos 6 pilares. Pra cada
   um, escreva uma frase: como o desenho atende (ou onde ele é fraco)? Esse é
   literalmente o exercício de um AS numa revisão de arquitetura.

3. **Decida uma troca.** O time quer substituir o SNS por "o Lambda manda e-mail
   direto". Liste 2 prós e 2 contras. Qual pilar cada opção favorece? Decida e
   registre num ADR (módulo 08).

4. **Desenhe uma solução nova.** Esqueça o projeto por um momento. Imagine "um
   sistema que recebe fotos de usuários, gera miniaturas e as guarda". Desenhe
   com as peças deste módulo (computação, storage, eventos). Não existe resposta
   única — treine montar a partir dos tipos de peça.

---

> **Resumo:** o Arquiteto de Soluções combina serviços de nuvem pra resolver
> necessidades de negócio, guiado pelos pilares (operação, segurança,
> confiabilidade, desempenho, custo, sustentabilidade) e pela responsabilidade
> compartilhada. Os modelos (IaaS→SaaS) trocam controle por conveniência. Montar
> uma solução é escolher e conectar os tipos de peça certos — e o
> `aws-cost-monitor` serverless mostra toda a trilha convergindo num desenho só.
>
> Próximo: **[10 — Projeto final e próximos passos](10-projeto-final-e-carreira.md)**.
