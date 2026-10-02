# ADR-006: Infraestrutura como código com AWS SAM

> Idioma: Português (Brasil) · [English](ADR-006-infrastructure-as-code-sam.md)

Status: aceito.

## Context

O backend deve ser reproduzível e revisável como código, implantável com scripts
documentados e validável offline (nenhuma implantação acontece a partir deste
repositório, e a SAM CLI não está instalada na máquina de desenvolvimento).

## Decision

Usar o AWS SAM (um transform do CloudFormation com atalhos para serverless). O
template declara o HTTP API, quatro funções com uma role IAM explícita cada, a
tabela única do DynamoDB, log groups por função e parâmetros para stage, nomes de
chave e retenção. A validação é offline com `cfn-lint`, que entende o transform
do SAM. Scripts de deploy/teardown/validate existem para PowerShell e Bash.

## Alternatives

- **AWS CDK**: imperativo e poderoso, mas adiciona uma toolchain Node.js e um app
  CDK para apenas quatro funções. Rejeitado.
- **Terraform**: excelente, mas introduz uma segunda linguagem e um backend de
  estado a gerenciar para um projeto solo. Rejeitado.
- **Console/click-ops**: não reproduzível nem revisável. Rejeitado.

## Consequences

- O template mapeia um-para-um com o diagrama de arquitetura; nenhum backend de
  estado a gerenciar (o CloudFormation mantém o estado).
- Validação offline via `cfn-lint`; `sam validate` fica anotado como verificação
  futura quando a SAM CLI estiver disponível.
- A verbosidade do CloudFormation para roles IAM é aceita em troca de menor
  privilégio explícito.
