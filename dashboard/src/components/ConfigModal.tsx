import React, { useState } from 'react'
import { CheckCircle2, Cloud, HardDrive, Key, Link2, Sparkles, X, XCircle } from 'lucide-react'
import type { ApiConfig } from '../types/diagnostic'
import { fetchHealth } from '../services/api'

interface ConfigModalProps {
  isOpen: boolean
  onClose: () => void
  config: ApiConfig
  onSave: (newConfig: ApiConfig) => void
}

export const ConfigModal: React.FC<ConfigModalProps> = ({
  isOpen,
  onClose,
  config,
  onSave,
}) => {
  const [baseUrl, setBaseUrl] = useState(config.baseUrl)
  const [readKey, setReadKey] = useState(config.readKey)
  const [isDemoMode, setIsDemoMode] = useState(config.isDemoMode)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null)

  if (!isOpen) return null

  const handleTestConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await fetchHealth({ baseUrl, readKey, isDemoMode: false })
      setTestResult({
        ok: true,
        msg: `Conexão bem-sucedida! Serviço: ${res.service}`,
      })
    } catch (err) {
      setTestResult({
        ok: false,
        msg: err instanceof Error ? err.message : 'Falha ao conectar com o endpoint.',
      })
    } finally {
      setTesting(false)
    }
  }

  const handleApplyPreset = (preset: 'local' | 'demo') => {
    if (preset === 'local') {
      setBaseUrl('http://127.0.0.1:8000')
      setReadKey('local-read-key')
      setIsDemoMode(false)
      setTestResult(null)
    } else if (preset === 'demo') {
      setIsDemoMode(true)
      setTestResult(null)
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSave({
      baseUrl: baseUrl.trim(),
      readKey: readKey.trim(),
      isDemoMode,
    })
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/40">
          <div className="flex items-center space-x-2">
            <Cloud className="w-5 h-5 text-indigo-400" />
            <h3 className="font-semibold text-white text-base">
              Configurações de Conexão da API
            </h3>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          {/* Quick Presets */}
          <div>
            <label className="text-xs font-medium text-slate-400 uppercase tracking-wider block mb-2">
              Atalhos de Configuração
            </label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => handleApplyPreset('demo')}
                className={`flex items-center space-x-2 px-3 py-2 rounded-xl text-xs font-medium border text-left transition ${
                  isDemoMode
                    ? 'bg-amber-500/15 border-amber-500/40 text-amber-300'
                    : 'bg-slate-800/60 border-slate-700/60 text-slate-300 hover:bg-slate-800'
                }`}
              >
                <Sparkles className="w-4 h-4 text-amber-400 shrink-0" />
                <div>
                  <div className="font-semibold">Modo Demonstração</div>
                  <div className="text-[11px] text-slate-400">Dados simulados offline</div>
                </div>
              </button>

              <button
                type="button"
                onClick={() => handleApplyPreset('local')}
                className={`flex items-center space-x-2 px-3 py-2 rounded-xl text-xs font-medium border text-left transition ${
                  !isDemoMode && baseUrl.includes('127.0.0.1:8000')
                    ? 'bg-indigo-500/15 border-indigo-500/40 text-indigo-300'
                    : 'bg-slate-800/60 border-slate-700/60 text-slate-300 hover:bg-slate-800'
                }`}
              >
                <HardDrive className="w-4 h-4 text-indigo-400 shrink-0" />
                <div>
                  <div className="font-semibold">Emulador Local</div>
                  <div className="text-[11px] text-slate-400">scripts/local_cloud.py</div>
                </div>
              </button>
            </div>
          </div>

          {/* Mode Switch */}
          <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950/40 border border-slate-800">
            <div>
              <span className="text-sm font-medium text-slate-200 block">
                Ativar Modo Demonstração
              </span>
              <span className="text-xs text-slate-400 block">
                Carrega 5 cenários determinísticos sem precisar de backend online
              </span>
            </div>
            <button
              type="button"
              onClick={() => setIsDemoMode(!isDemoMode)}
              className={`w-12 h-6 flex items-center rounded-full p-1 transition-colors duration-200 ${
                isDemoMode ? 'bg-indigo-600 justify-end' : 'bg-slate-700 justify-start'
              }`}
            >
              <div className="bg-white w-4 h-4 rounded-full shadow-md" />
            </button>
          </div>

          {/* API URL */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-300 flex items-center space-x-1.5">
              <Link2 className="w-3.5 h-3.5 text-slate-400" />
              <span>URL Base da API (HTTP API Gateway ou Emulador)</span>
            </label>
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://xxx.execute-api.us-east-1.amazonaws.com/dev ou http://127.0.0.1:8000"
              disabled={isDemoMode}
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950/70 border border-slate-700 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent disabled:opacity-40"
            />
          </div>

          {/* Read API Key */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-300 flex items-center space-x-1.5">
              <Key className="w-3.5 h-3.5 text-slate-400" />
              <span>Chave de Leitura (Bearer READ_KEY)</span>
            </label>
            <input
              type="password"
              value={readKey}
              onChange={(e) => setReadKey(e.target.value)}
              placeholder="Chave SSM SecureString com escopo 'read'"
              disabled={isDemoMode}
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950/70 border border-slate-700 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent disabled:opacity-40"
            />
            <p className="text-[11px] text-slate-400">
              Usa apenas permissão de consulta (<code>read</code>). A chave de ingestão nunca é exposta no navegador.
            </p>
          </div>

          {/* Test Connection Button & Result */}
          {!isDemoMode && (
            <div className="space-y-2 pt-1">
              <button
                type="button"
                onClick={handleTestConnection}
                disabled={testing || !baseUrl}
                className="w-full py-2 px-3 rounded-xl bg-slate-800 hover:bg-slate-700/80 text-xs font-medium text-slate-200 border border-slate-700 transition flex items-center justify-center space-x-2 disabled:opacity-50"
              >
                <Cloud className="w-4 h-4 text-indigo-400" />
                <span>{testing ? 'Testando conexão...' : 'Testar Conexão com Endpoint'}</span>
              </button>

              {testResult && (
                <div
                  className={`p-3 rounded-xl text-xs flex items-start space-x-2 border ${
                    testResult.ok
                      ? 'bg-emerald-950/40 text-emerald-300 border-emerald-800/60'
                      : 'bg-rose-950/40 text-rose-300 border-rose-800/60'
                  }`}
                >
                  {testResult.ok ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                  ) : (
                    <XCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                  )}
                  <span className="break-all">{testResult.msg}</span>
                </div>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-end space-x-3 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-medium text-slate-300 hover:text-white hover:bg-slate-800 transition"
            >
              Cancelar
            </button>
            <button
              type="submit"
              className="px-5 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold text-white shadow-lg shadow-indigo-600/30 transition"
            >
              Salvar Alterações
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
