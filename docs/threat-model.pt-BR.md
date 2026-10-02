# Modelo de ameaças

> Idioma: Português (Brasil) · [English](threat-model.md)

Nove ameaças, cada uma com impacto, mitigação e risco residual. O sistema usa uma
única chave de ingestão compartilhada (credenciais por dispositivo são trabalho
futuro), o que molda vários dos riscos residuais abaixo.

### 1. Chave de ingestão roubada ou vazada

- **Impacto**: um atacante pode enviar telemetria e forjar IDs de outros
  dispositivos.
- **Mitigação**: armazenamento em SecureString, apenas HTTPS, o wrapper `Secret`
  e redação de log no agente, o log de acesso retém o `sourceIp` como evidência,
  rotação de chave suportada sem indisponibilidade.
- **Residual**: uma chave vazada é usável até ser rotacionada; a atribuição conta
  com o `sourceIp`. Credenciais por dispositivo removeriam isso; aceito para a
  v1.

### 2. Replay de uma requisição capturada

- **Impacto**: uma requisição de telemetria capturada poderia ser reenviada.
- **Mitigação**: ingestão idempotente baseada em `event_id` (put condicional) e
  uma janela de clock skew rejeita timestamps futuros; um replay é um duplicata
  no-op.
- **Residual**: uma requisição capturada pode ser reenviada como no-op; não pode
  criar um segundo item armazenado nem alterar um existente.

### 3. Man-in-the-middle / redirecionamento para host hostil

- **Impacto**: interceptação ou roubo da chave Bearer.
- **Mitigação**: verificação de certificado TLS por padrão; o transporte recusa
  todos os redirecionamentos para que a chave nunca seja copiada a outro host; um
  redirecionamento é `CONFIG_ERROR`.
- **Residual**: um comprometimento de CA confiável no nível do host está fora de
  escopo.

### 4. Roubo de credencial a partir de logs ou saída

- **Impacto**: uma chave poderia vazar por logs ou `status`.
- **Mitigação**: wrapper `Secret` (`***`), um filtro de redação nos extras de
  log e um teste de vazamento de segredo com uma chave sentinela.
- **Residual**: um atacante com acesso ao sistema de arquivos local ao `.env` em
  texto puro já controla o host; isso está fora da fronteira de confiança da API.

### 5. Injeção via payloads de telemetria

- **Impacto**: payloads malformados ou grandes demais poderiam quebrar um handler
  ou envenenar o armazenamento.
- **Mitigação**: validação estrita de schema, rejeição de campos desconhecidos,
  limites de tamanho (8 KiB registro, 256 KiB telemetria, 32 KiB por evento),
  rejeição de `bool` como número; payloads são armazenados como strings JSON, não
  avaliados.
- **Residual**: valores bem formados mas enganosos são aceitos; são dados de
  diagnóstico, não executados.

### 6. Negação de serviço / amplificação de custo

- **Impacto**: uma enxurrada de requisições eleva custo ou latência.
- **Mitigação**: throttling do API Gateway (taxa + burst), pequenos limites por
  requisição, DynamoDB sob demanda, funções de 128 MB com timeout curto.
- **Residual**: um atacante determinado com uma chave válida ainda pode gerar
  custo; limitado por throttling e alarmes (alarmes são trabalho futuro).

### 7. Escalonamento de privilégio entre funções

- **Impacto**: uma função comprometida alcançando os dados de outra.
- **Mitigação**: uma role de menor privilégio por função, sem ações curinga,
  recursos de log restritos por função, SSM restrito aos dois ARNs de parâmetro.
- **Residual**: todas as funções podem ler as duas chaves (precisam
  autenticar); aceitável dado o modelo de chave compartilhada.

### 8. Exposição de dados pela API de leitura

- **Impacto**: uma chave de leitura poderia expor formatos internos de
  armazenamento ou PII.
- **Mitigação**: um único mapeamento `to_public` remove chaves internas; o agente
  minimiza e limpa os dados antes do envio, então há pouco conteúdo sensível a
  expor; um teste unitário afirma que nenhuma chave interna vaza.
- **Residual**: uma chave de leitura vazada expõe o inventário de dispositivos e
  diagnósticos (não PII) até ser rotacionada.

### 9. Cursor de paginação adulterado

- **Impacto**: um cursor forjado poderia ler entre dispositivos.
- **Mitigação**: o cursor de diagnósticos é vinculado ao seu `device_id` e
  validado na decodificação; um cursor adulterado é `INVALID_CURSOR` (400).
- **Residual**: nenhum além do que o escopo de leitura já permite.
