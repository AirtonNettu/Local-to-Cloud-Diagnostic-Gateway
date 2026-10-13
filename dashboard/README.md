# Diagnostic Gateway Dashboard

Painel web moderno, reativo e responsivo para visualização e observabilidade de nós e frotas do **Local-to-Cloud Diagnostic Gateway**.

## Recursos

- **Visão Geral da Frota (Fleet Overview)**: KPIs de nós totais, saudáveis, degradados, críticos e desconectados com busca e filtros rápidos.
- **Detalhamento do Nó (Device Detail)**:
  - Medidores de telemetria em tempo real: Uso de CPU, memória RAM física, capacidade de disco C: e latência/perda de pacotes.
  - Verificações de Diagnóstico (*Checks*) com status `PASS`, `WARN` ou `FAIL` e inspeção detalhada de evidências.
  - Alertas ativos e regras de conformidade disparadas.
  - Fatos de hardware coletados (modelo de processador, cores, memória, versão do sistema operacional e do agente).
  - Linha do tempo de execuções de diagnóstico anteriores.
- **Modos de Operação**:
  - **Modo Demonstração (Demo)**: Carrega instantaneamente dados e cenários simulados sem precisar de backend ou internet.
  - **Emulador Local**: Conecta ao script `scripts/local_cloud.py` (`http://127.0.0.1:8000`).
  - **AWS Cloud Live**: Conecta ao endpoint real do HTTP API Gateway da AWS com chave Bearer `read`.

## Como Executar Localmente

No Windows, você pode simplesmente dar dois cliques no menu:
- `MENU.bat` e escolher a opção `9`
- ou abrir diretamente `atalhos\9-Dashboard.bat`.

Ou via linha de comando dentro da pasta `dashboard`:

```bash
npm install
npm run dev
```

O dashboard abrirá em `http://localhost:5173`.

## Publicação Online Gratuita (Zero Verba)

### Na Vercel (Recomendado)
1. Suba o repositório para o seu GitHub.
2. Acesse [vercel.com](https://vercel.com) e crie uma conta gratuita.
3. Importe o repositório e configure:
   - **Root Directory**: `dashboard`
   - **Build Command**: `npm run build`
   - **Output Directory**: `dist`
4. Clique em **Deploy**. Você receberá um domínio gratuito com HTTPS automático (ex: `diagnostic-gateway.vercel.app`).

### No Cloudflare Pages ou GitHub Pages
Também pode ser publicado diretamente via `npm run build`, apontando a pasta de saída para `dist`.
