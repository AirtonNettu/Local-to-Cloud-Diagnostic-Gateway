# Custo

> Idioma: Português (Brasil) · [English](cost.md)

O backend é serverless e pay-per-use, então o custo ocioso é quase zero. Este
documento lista os serviços, os direcionadores de custo, como o design minimiza
custo e como derrubar tudo.

## Serviços e modelo de custo

| Serviço | Cobrado por |
|---|---|
| HTTP API Gateway | por milhão de requisições |
| Lambda | por requisição + GB-segundos (128 MB, `arm64`) |
| DynamoDB | unidades de requisição de leitura/escrita sob demanda + bytes armazenados |
| CloudWatch Logs | GB ingeridos + GB armazenados (retenção de 14 dias) |
| Métricas customizadas do CloudWatch (EMF) | por nome de métrica × dimensão por mês |
| SSM Parameter Store | SecureStrings padrão são gratuitas |

## Direcionadores de custo

- **Volume de requisições**: com telemetria horária por dispositivo a contagem de
  requisições é minúscula; o custo escala com o número de dispositivos e a
  frequência de scan.
- **Ingestão de logs**: logs estruturados são pequenos e a retenção é de 14 dias.
- **Armazenamento no DynamoDB**: eventos expiram por TTL (padrão 30 dias),
  limitando o crescimento.
- **Métricas customizadas**: veja a nota abaixo.

## Nota sobre cobrança de métricas customizadas EMF

As métricas customizadas do CloudWatch são cobradas **por combinação de nome de
métrica × dimensão por mês**, e apenas nas horas em que uma métrica realmente
emite um ponto de dado (não há cobrança por um nome de métrica que fica em
silêncio o mês inteiro). Este projeto define oito nomes de métrica
(`DeviceRegistered`, `TelemetryAccepted`, `TelemetryDuplicate`,
`TelemetryRejected`, `ValidationError`, `AuthFailure`, `DynamoDBError`,
`LambdaError`) sob um conjunto de dimensões `[["Service", "Function"]]`. Como o
valor da dimensão `Function` varia por função emissora, a contagem realista é de
aproximadamente **10–12 métricas customizadas cobráveis** nos meses em que o
backend está ativo, e zero em meses sem tráfego. Manter `device_id` fora das
dimensões é deliberado: uma dimensão de alta cardinalidade multiplicaria esse
custo drasticamente.

## Minimização

- DynamoDB sob demanda (sem capacidade provisionada a pagar enquanto ocioso).
- Funções Lambda `arm64` de 128 MB com timeout curto.
- Retenção de log de 14 dias e TTL nos eventos de diagnóstico.
- Um conjunto baixo e fixo de nomes de métrica EMF com uma única dimensão de baixa
  cardinalidade.
- O throttling do API Gateway limita um chamador descontrolado ou hostil.
- Point-in-time recovery está desligado por padrão (um trade-off documentado).

## Teardown

Apagar o stack SAM/CloudFormation remove tudo que é cobrável. O template define
`DeletionPolicy: Delete` na tabela e em todos os log groups, então um delete do
stack não deixa nada para trás. Use `scripts/teardown.{ps1,sh}`. Os parâmetros
SSM SecureString são criados fora do stack e devem ser apagados separadamente
quando não forem mais necessários.
