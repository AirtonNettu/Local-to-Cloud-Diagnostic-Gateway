# Segurança

> Idioma: Português (Brasil) · [English](security.md)

## Transporte

Todo o tráfego para a nuvem é HTTPS no endpoint padrão `execute-api` (TLS 1.2+).
O transporte `urllib` do agente verifica certificados TLS por padrão e recusa
todo redirecionamento, de modo que a chave de ingestão nunca é reenviada a um
destino de redirecionamento. Um redirecionamento é tratado como erro de
configuração.

## Autenticação e autorização

A autenticação é uma chave de API Bearer. Há duas chaves com escopo:

- `ingest` — usada por agentes para registrar e enviar telemetria (escrita).
- `read` — usada por operadores para listar e ler (leitura).

As chaves são armazenadas como SSM SecureStrings e carregadas pelas funções
Lambda com uma única chamada `GetParameters(WithDecryption=True)`, cacheadas por
cinco minutos, mantendo um valor obsoleto se um refresh falhar (rotação sem
indisponibilidade). O token vem de um header não confiável, então é parseado de
forma defensiva e comparado em bytes com `hmac.compare_digest`; ambas as
comparações de chave sempre rodam para que o tempo de resposta nunca revele qual
chave estava mais próxima. Um token não-ASCII é rejeitado como 401, não 500. As
chaves nunca são logadas.

## Matriz de IAM

Uma role explícita por função, sem managed policies, sem ações curinga.

| Função | Logs | DynamoDB | SSM |
|---|---|---|---|
| health | apenas o próprio log group | nenhum | nenhum |
| device | o próprio log group | `GetItem`, `UpdateItem`, `Query` (tabela + GSI1) | `GetParameters` nos dois ARNs de chave |
| telemetry | o próprio log group | `GetItem`, `PutItem`, `UpdateItem` (tabela) | `GetParameters` nos dois ARNs de chave |
| diagnostic | o próprio log group | `GetItem`, `Query` (tabela) | `GetParameters` nos dois ARNs de chave |

Cada recurso de log é restrito ao ARN do log group daquela função. A
descriptografia KMS das SecureStrings usa a chave gerenciada pela AWS
`alias/aws/ssm`.

## Segredos

A chave de ingestão e a chave de leitura nunca aparecem em código, logs ou na
saída de `status`. No agente, elas são embrulhadas em um tipo `Secret` cujo
`repr`/`str` retornam `***`, e um filtro de redação de log descarta qualquer
chave extra que case com `key|token|secret|password|authorization`. Um teste de
vazamento de segredo roda uma sincronização com uma chave sentinela e afirma que
ela não aparece em nenhum registro ou arquivo de log capturado.

## Validação de entrada

O schema compartilhado em `shared/schemas` é o único contrato. A nuvem o impõe em
toda requisição e o agente pré-verifica todo payload que constrói com o mesmo
código, de modo que um teste de contrato prova que a saída do agente é sempre
aceitável. Os validadores reportam todos os problemas de uma vez, rejeitam campos
desconhecidos e rejeitam `bool` onde se espera um número. Os detalhes de erro
carregam apenas nomes de campo e descrições de problema, nunca valores de campo.

## Minimização de dados

O agente envia uma lista branca explícita de campos. Evidências e mensagens são
limpas de literais de IP (substituídos por `<ip>`) e truncadas aos limites do
schema, de modo que nomes de interface, servidores DNS e IPs de gateway nunca
saem do host. Strings de modelo de disco físico e de GPU ficam nos fatos locais e
são estruturalmente excluídas de checks, alerts e metrics (discos são
referenciados por posição, `disk{index}`). O agente nunca coleta histórico de
navegação, documentos, teclas digitadas, capturas de tela, endereços MAC, números
de série ou nomes de usuário.

## Retenção de sourceIp

O log de acesso da API retém o `sourceIp` de quem chama. Esta é uma exceção
deliberada à minimização: é evidência para as ameaças de chave roubada e abuso
(uma única chave de ingestão compartilhada não poderia, de outra forma, ser
atribuída a quem chamou). Ela é mantida apenas no log group de acesso sob a
retenção de log configurada (14 dias por padrão) e nunca é armazenada no DynamoDB
nem retornada pela API.

## Fronteiras de confiança (§44)

```text
LOCAL TRUST DOMAIN  (agent + local SQLite + .env on a user-controlled machine)
        │  HTTPS, Bearer token
        ▼
PUBLIC API          (anything reaching API Gateway is untrusted)
        │
        ▼
AWS APPLICATION     (trusted: Lambda code and its IAM roles)
        │
        ▼
DATABASE            (reachable only via the function roles)
```

- **Confiável**: o agente e seu banco local e `.env` na própria máquina do
  usuário; o código do Lambda e suas roles.
- **Não confiável**: a internet pública e qualquer requisição que alcance o API
  Gateway (autenticada ou não) até que auth e validação passem.
- DynamoDB e SSM só são alcançáveis pelas roles das funções, nunca diretamente da
  internet.
