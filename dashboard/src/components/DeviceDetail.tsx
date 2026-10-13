import React, { useState } from 'react'
import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Cpu,
  Database,
  Globe,
  HardDrive,
  Info,
  Layers,
  ShieldCheck,
  Terminal,
  Wifi,
  WifiOff,
} from 'lucide-react'
import type { DeviceProfile, DiagnosticEvent } from '../types/diagnostic'

interface DeviceDetailProps {
  device: DeviceProfile
  diagnostics: DiagnosticEvent[]
  isLoadingDiagnostics: boolean
  onBack: () => void
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

export const DeviceDetail: React.FC<DeviceDetailProps> = ({
  device,
  diagnostics,
  isLoadingDiagnostics,
  onBack,
}) => {
  const [selectedEventIndex, setSelectedEventIndex] = useState(0)
  const [expandedCheck, setExpandedCheck] = useState<string | null>(null)
  const [checkFilter, setCheckFilter] = useState<'ALL' | 'PASS' | 'WARN' | 'FAIL'>('ALL')

  const currentEvent = diagnostics[selectedEventIndex] || null

  // Extract key metrics from the current event
  const cpuMetric = currentEvent?.metrics.find((m) => m.name === 'cpu_percent')
  const memMetric = currentEvent?.metrics.find((m) => m.name === 'memory_percent')
  const storageMetric = currentEvent?.metrics.find((m) => m.name === 'storage_used_percent')
  const netLatencyMetric = currentEvent?.metrics.find((m) => m.name === 'network_latency_ms')
  const packetLossMetric = currentEvent?.metrics.find((m) => m.name === 'packet_loss_percent')

  // Filter checks
  const filteredChecks = currentEvent?.checks.filter((c) => {
    if (checkFilter === 'ALL') return true
    return c.status === checkFilter
  }) || []

  return (
    <div className="space-y-6">
      {/* Top Nav: Back Button & Title */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-4">
        <div className="flex items-center space-x-3">
          <button
            onClick={onBack}
            className="p-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-800 transition shadow-sm"
            title="Voltar para a lista de nós"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <div className="flex items-center space-x-2">
              <h2 className="text-xl font-bold text-white tracking-tight">
                {device.device_name}
              </h2>
              <span className="text-xs px-2.5 py-0.5 rounded-full font-mono bg-slate-800/80 text-slate-400 border border-slate-700/80">
                {device.device_id}
              </span>
            </div>
            <div className="text-xs text-slate-400 mt-0.5 flex items-center space-x-2">
              <span>{device.os.name} {device.os.version} ({device.os.architecture})</span>
              <span>•</span>
              <span>Agente v{device.agent_version}</span>
            </div>
          </div>
        </div>

        {/* Status Pills */}
        <div className="flex items-center space-x-2">
          {/* Health Status */}
          <div
            className={`flex items-center space-x-1.5 px-3 py-1 rounded-xl text-xs font-semibold border ${
              (currentEvent?.status || device.latest?.status) === 'HEALTHY'
                ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                : (currentEvent?.status || device.latest?.status) === 'DEGRADED'
                ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                : 'bg-rose-500/10 text-rose-300 border-rose-500/30'
            }`}
          >
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>Saúde: {currentEvent?.status || device.latest?.status || 'HEALTHY'}</span>
          </div>

          {/* Network Status */}
          <div
            className={`flex items-center space-x-1.5 px-3 py-1 rounded-xl text-xs font-semibold border ${
              (currentEvent?.network_status || device.latest?.network_status) === 'OFFLINE'
                ? 'bg-rose-500/10 text-rose-300 border-rose-500/30'
                : (currentEvent?.network_status || device.latest?.network_status) === 'DEGRADED' ||
                  (currentEvent?.network_status || device.latest?.network_status) === 'UNSTABLE'
                ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                : 'bg-indigo-500/10 text-indigo-300 border-indigo-500/30'
            }`}
          >
            {(currentEvent?.network_status || device.latest?.network_status) === 'OFFLINE' ? (
              <WifiOff className="w-3.5 h-3.5" />
            ) : (
              <Wifi className="w-3.5 h-3.5" />
            )}
            <span>Rede: {currentEvent?.network_status || device.latest?.network_status || 'UNKNOWN'}</span>
          </div>
        </div>
      </div>

      {/* Real-time Telemetry Metrics Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* CPU */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4.5">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="font-medium">Uso de Processador (CPU)</span>
            <Cpu className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="mt-2.5 flex items-baseline justify-between">
            <span className="text-3xl font-bold text-white tracking-tight">
              {cpuMetric !== undefined ? `${cpuMetric.value.toFixed(1)}%` : '—'}
            </span>
            <span className="text-xs text-slate-400">
              {device.hardware.logical_cpus} threads
            </span>
          </div>
          {/* Progress bar */}
          <div className="w-full bg-slate-800 h-2 rounded-full mt-3 overflow-hidden">
            <div
              className={`h-full transition-all duration-300 ${
                (cpuMetric?.value ?? 0) > 90
                  ? 'bg-rose-500'
                  : (cpuMetric?.value ?? 0) > 75
                  ? 'bg-amber-500'
                  : 'bg-indigo-500'
              }`}
              style={{ width: `${Math.min(cpuMetric?.value ?? 0, 100)}%` }}
            />
          </div>
        </div>

        {/* Memory */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4.5">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="font-medium">Memória Física (RAM)</span>
            <Database className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="mt-2.5 flex items-baseline justify-between">
            <span className="text-3xl font-bold text-white tracking-tight">
              {memMetric !== undefined ? `${memMetric.value.toFixed(1)}%` : '—'}
            </span>
            <span className="text-xs text-slate-400">
              Total {formatBytes(device.hardware.memory_total_bytes)}
            </span>
          </div>
          <div className="w-full bg-slate-800 h-2 rounded-full mt-3 overflow-hidden">
            <div
              className={`h-full transition-all duration-300 ${
                (memMetric?.value ?? 0) > 90
                  ? 'bg-rose-500'
                  : (memMetric?.value ?? 0) > 75
                  ? 'bg-amber-500'
                  : 'bg-indigo-500'
              }`}
              style={{ width: `${Math.min(memMetric?.value ?? 0, 100)}%` }}
            />
          </div>
        </div>

        {/* Storage */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4.5">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="font-medium">Armazenamento (Disco C:)</span>
            <HardDrive className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="mt-2.5 flex items-baseline justify-between">
            <span className="text-3xl font-bold text-white tracking-tight">
              {storageMetric !== undefined ? `${storageMetric.value.toFixed(1)}%` : '—'}
            </span>
            <span className="text-xs text-slate-400">ocupado</span>
          </div>
          <div className="w-full bg-slate-800 h-2 rounded-full mt-3 overflow-hidden">
            <div
              className={`h-full transition-all duration-300 ${
                (storageMetric?.value ?? 0) > 95
                  ? 'bg-rose-500'
                  : (storageMetric?.value ?? 0) > 85
                  ? 'bg-amber-500'
                  : 'bg-indigo-500'
              }`}
              style={{ width: `${Math.min(storageMetric?.value ?? 0, 100)}%` }}
            />
          </div>
        </div>

        {/* Network Probes */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4.5">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="font-medium">Probes de Rede & Latência</span>
            <Globe className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="mt-2.5 flex items-baseline justify-between">
            <span className="text-3xl font-bold text-white tracking-tight">
              {netLatencyMetric !== undefined
                ? `${Math.round(netLatencyMetric.value)} ms`
                : '—'}
            </span>
            <span
              className={`text-xs font-semibold ${
                (packetLossMetric?.value ?? 0) > 0 ? 'text-amber-400' : 'text-emerald-400'
              }`}
            >
              Perda: {packetLossMetric?.value ?? 0}%
            </span>
          </div>
          <div className="w-full bg-slate-800 h-2 rounded-full mt-3 overflow-hidden">
            <div
              className={`h-full transition-all duration-300 ${
                (packetLossMetric?.value ?? 0) > 20
                  ? 'bg-rose-500'
                  : (packetLossMetric?.value ?? 0) > 0
                  ? 'bg-amber-500'
                  : 'bg-emerald-500'
              }`}
              style={{ width: `${Math.max(100 - (packetLossMetric?.value ?? 0), 5)}%` }}
            />
          </div>
        </div>
      </div>

      {/* Event Timeline Selector */}
      {diagnostics.length > 1 && (
        <div className="p-4 rounded-2xl bg-slate-900/40 border border-slate-800">
          <div className="text-xs font-semibold text-slate-300 mb-2 flex items-center space-x-1.5">
            <Clock className="w-3.5 h-3.5 text-indigo-400" />
            <span>Linha do Tempo de Execuções de Diagnóstico ({diagnostics.length} registradas)</span>
          </div>
          <div className="flex items-center space-x-2 overflow-x-auto pb-1 text-xs">
            {diagnostics.map((event, idx) => (
              <button
                key={event.event_id}
                onClick={() => setSelectedEventIndex(idx)}
                className={`px-3 py-1.5 rounded-xl border text-left shrink-0 transition ${
                  selectedEventIndex === idx
                    ? 'bg-indigo-600/30 border-indigo-500 text-white shadow-sm'
                    : 'bg-slate-800/60 border-slate-700/60 text-slate-300 hover:bg-slate-800'
                }`}
              >
                <div className="font-mono text-[11px] font-bold">
                  {new Date(event.timestamp).toLocaleTimeString('pt-BR')}
                </div>
                <div className="text-[10px] text-slate-400">
                  {event.status} • {event.checks.length} checks
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Main Content Columns: Checks & Alerts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Diagnostic Checks (2 cols wide) */}
        <div className="lg:col-span-2 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div className="flex items-center space-x-2">
              <Layers className="w-4 h-4 text-indigo-400" />
              <h3 className="text-sm font-semibold text-white">
                Verificações de Diagnóstico (Rules & Probes)
              </h3>
            </div>

            {/* Filter Buttons */}
            <div className="flex items-center space-x-1 text-xs">
              {(['ALL', 'PASS', 'WARN', 'FAIL'] as const).map((filter) => (
                <button
                  key={filter}
                  onClick={() => setCheckFilter(filter)}
                  className={`px-2.5 py-1 rounded-lg font-medium transition ${
                    checkFilter === filter
                      ? 'bg-slate-800 text-white border border-slate-700'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {filter === 'ALL' ? 'Todos' : filter}
                </button>
              ))}
            </div>
          </div>

          {isLoadingDiagnostics ? (
            <div className="py-12 text-center text-xs text-slate-400">
              Carregando checks de diagnóstico...
            </div>
          ) : filteredChecks.length === 0 ? (
            <div className="p-8 text-center text-xs text-slate-500 bg-slate-900/40 rounded-2xl border border-slate-800">
              Nenhuma verificação nesta categoria.
            </div>
          ) : (
            <div className="space-y-2.5">
              {filteredChecks.map((check) => {
                const isExpanded = expandedCheck === check.name

                return (
                  <div
                    key={check.name}
                    className="bg-slate-900/60 border border-slate-800/80 rounded-xl overflow-hidden transition"
                  >
                    <div
                      onClick={() => setExpandedCheck(isExpanded ? null : check.name)}
                      className="p-3.5 flex items-center justify-between cursor-pointer hover:bg-slate-800/40"
                    >
                      <div className="flex items-start space-x-3">
                        <div className="mt-0.5">
                          {check.status === 'PASS' ? (
                            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                          ) : check.status === 'WARN' ? (
                            <AlertTriangle className="w-4 h-4 text-amber-400" />
                          ) : (
                            <AlertCircle className="w-4 h-4 text-rose-400" />
                          )}
                        </div>
                        <div>
                          <div className="font-mono text-xs font-semibold text-white">
                            {check.name}
                          </div>
                          <div className="text-xs text-slate-300 mt-0.5">
                            {check.summary}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center space-x-2 text-slate-400">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            check.status === 'PASS'
                              ? 'bg-emerald-500/10 text-emerald-300'
                              : check.status === 'WARN'
                              ? 'bg-amber-500/10 text-amber-300'
                              : 'bg-rose-500/10 text-rose-300'
                          }`}
                        >
                          {check.status}
                        </span>
                        {isExpanded ? (
                          <ChevronDown className="w-4 h-4 text-slate-400" />
                        ) : (
                          <ChevronRight className="w-4 h-4 text-slate-500" />
                        )}
                      </div>
                    </div>

                    {/* Expandable Evidence Payload */}
                    {isExpanded && check.evidence && (
                      <div className="p-3.5 bg-slate-950/80 border-t border-slate-800/60 text-xs font-mono">
                        <div className="text-[11px] font-sans font-semibold text-slate-400 mb-1 flex items-center space-x-1.5">
                          <Terminal className="w-3.5 h-3.5 text-indigo-400" />
                          <span>Evidências Coletadas:</span>
                        </div>
                        <pre className="text-slate-300 overflow-x-auto p-2 bg-slate-900 rounded-lg text-[11px]">
                          {JSON.stringify(check.evidence, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Right Column: Active Alerts & Hardware Specs */}
        <div className="space-y-6">
          {/* Alerts Box */}
          <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4.5 space-y-3">
            <div className="flex items-center space-x-2 border-b border-slate-800 pb-2.5">
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              <h3 className="text-sm font-semibold text-white">
                Alertas da Execução ({currentEvent?.alerts.length || 0})
              </h3>
            </div>

            {(!currentEvent?.alerts || currentEvent.alerts.length === 0) ? (
              <div className="p-4 rounded-xl bg-emerald-950/20 border border-emerald-900/30 text-xs text-emerald-300 flex items-center space-x-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                <span>Nenhum alerta disparado. Todos os limiares estão normais.</span>
              </div>
            ) : (
              <div className="space-y-2">
                {currentEvent.alerts.map((alert, i) => (
                  <div
                    key={i}
                    className={`p-3 rounded-xl border text-xs ${
                      alert.severity === 'CRITICAL'
                        ? 'bg-rose-950/30 border-rose-800/60 text-rose-200'
                        : 'bg-amber-950/30 border-amber-800/60 text-amber-200'
                    }`}
                  >
                    <div className="flex items-center justify-between font-mono font-bold text-[11px] mb-1">
                      <span>{alert.rule_id}</span>
                      <span className="uppercase text-[10px] px-1.5 py-0.5 rounded bg-black/40">
                        {alert.severity}
                      </span>
                    </div>
                    <p className="font-sans text-xs leading-relaxed">{alert.message}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Hardware & System Details Card */}
          <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4.5 space-y-3">
            <div className="flex items-center space-x-2 border-b border-slate-800 pb-2.5">
              <Info className="w-4 h-4 text-indigo-400" />
              <h3 className="text-sm font-semibold text-white">Especificações do Host</h3>
            </div>

            <div className="space-y-2.5 text-xs">
              <div className="flex justify-between items-center text-slate-400">
                <span>Processador</span>
                <span className="font-semibold text-slate-200 text-right max-w-[180px] truncate">
                  {device.hardware.cpu_model}
                </span>
              </div>
              <div className="flex justify-between items-center text-slate-400">
                <span>Cores Físicos / Lógicos</span>
                <span className="font-semibold text-slate-200">
                  {device.hardware.physical_cores} / {device.hardware.logical_cpus}
                </span>
              </div>
              <div className="flex justify-between items-center text-slate-400">
                <span>Memória Instalada</span>
                <span className="font-semibold text-slate-200">
                  {formatBytes(device.hardware.memory_total_bytes)}
                </span>
              </div>
              <div className="flex justify-between items-center text-slate-400">
                <span>Sistema Operacional</span>
                <span className="font-semibold text-slate-200">
                  {device.os.name} ({device.os.architecture})
                </span>
              </div>
              <div className="flex justify-between items-center text-slate-400">
                <span>Cadastrado em</span>
                <span className="font-semibold text-slate-200">
                  {new Date(device.registered_at).toLocaleDateString('pt-BR')}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
