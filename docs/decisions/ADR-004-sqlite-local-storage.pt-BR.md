# ADR-004: SQLite para armazenamento local

> Idioma: Português (Brasil) · [English](ADR-004-sqlite-local-storage.md)

Status: aceito.

## Context

O design local-first (ADR-001) precisa de armazenamento durável, transacional e
sem configuração para execuções, resultados e a fila de sincronização na máquina
do usuário, sem servidor a instalar e sem dependência extra.

## Decision

Usar o módulo `sqlite3` da biblioteca padrão em modo WAL com foreign keys ativas.
As migrações são indexadas por `PRAGMA user_version`; `PRAGMA application_id`
marca bancos live versus demo para que o modo demo nunca apague um arquivo que
não criou. Cada execução persiste sua linha, resultados e (opcionalmente) um
evento de fila em uma única transação `BEGIN IMMEDIATE`. Comandos somente leitura
abrem uma URI `mode=ro` e nunca migram.

## Alternatives

- **Arquivos planos (JSON/CSV)**: sem transações nem fila segura para
  concorrência; reinventaria o locking. Rejeitado.
- **Um servidor embutido (por exemplo, Postgres local)**: instalar e rodar um
  servidor em uma máquina de borda. Rejeitado.

## Consequences

- Nenhuma dependência de terceiros e nenhuma configuração; o arquivo é o banco.
- A persistência atômica garante a invariante execução/fila.
- A concorrência é limitada pelo modelo de escritor único do SQLite, suficiente
  para um processo de agente; um banco travado aparece como um erro limpo de
  exit 1.
