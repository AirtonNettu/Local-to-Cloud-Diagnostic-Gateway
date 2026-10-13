import React, { useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Cpu,
  HardDrive,
  Laptop,
  Monitor,
  Search,
  Server,
  ShieldAlert,
  Wifi,
  WifiOff,
} from 'lucide-react'
import type { DeviceProfile } from '../types/diagnostic'

interface FleetOverviewProps {
  devices: DeviceProfile[]
  onSelectDevice: (deviceId: string) => void
  isLoading: boolean
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

function formatRelativeTime(isoString?: string): string {
  if (!isoString) return 'Nunca visto'
  const date = new Date(isoString)
  const now = new Date()
  const diffSec = Math.floor((now.getTime() - date.getTime()) / 1000)

  if (diffSec < 60) return 'Agora mesmo'
  if (diffSec < 3600) return `Há ${Math.floor(diffSec / 60)}m`
  if (diffSec < 86400) return `Há ${Math.floor(diffSec / 3600)}h`
  return `Há ${Math.floor(diffSec / 86400)}d`
}

export const FleetOverview: React.FC<FleetOverviewProps> = ({
  devices,
  onSelectDevice,
  isLoading,
}) => {
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'HEALTHY' | 'DEGRADED' | 'CRITICAL' | 'OFFLINE'>('ALL')

  // Calculate KPIs
  const total = devices.length
  const healthyCount = devices.filter((d) => d.latest?.status === 'HEALTHY').length
  const degradedCount = devices.filter(
    (d) => d.latest?.status === 'DEGRADED' && d.latest?.network_status !== 'OFFLINE'
  ).length
  const criticalCount = devices.filter((d) => d.latest?.status === 'CRITICAL').length
  const offlineCount = devices.filter((d) => d.latest?.network_status === 'OFFLINE').length

  // Filter devices
  const filteredDevices = devices.filter((device) => {
    const matchesSearch =
      device.device_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      device.device_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      device.hardware.cpu_model.toLowerCase().includes(searchTerm.toLowerCase())

    if (!matchesSearch) return false

    if (statusFilter === 'ALL') return true
    if (statusFilter === 'OFFLINE') return device.latest?.network_status === 'OFFLINE'
    return device.latest?.status === statusFilter
  })

  return (
    <div className="space-y-6">
      {/* KPI Cards Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3.5 sm:gap-4">
        {/* Total */}
        <div
          onClick={() => setStatusFilter('ALL')}
          className={`cursor-pointer p-4 rounded-2xl border transition-all duration-150 ${
            statusFilter === 'ALL'
              ? 'bg-indigo-950/40 border-indigo-500/60 ring-1 ring-indigo-500/30'
              : 'bg-slate-900/60 border-slate-800 hover:border-slate-700'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Total de Nós</span>
            <Server className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="mt-2 flex items-baseline space-x-2">
            <span className="text-2xl sm:text-3xl font-bold text-white tracking-tight">
              {total}
            </span>
            <span className="text-xs text-slate-400">máquinas</span>
          </div>
        </div>

        {/* Healthy */}
        <div
          onClick={() => setStatusFilter('HEALTHY')}
          className={`cursor-pointer p-4 rounded-2xl border transition-all duration-150 ${
            statusFilter === 'HEALTHY'
              ? 'bg-emerald-950/40 border-emerald-500/60 ring-1 ring-emerald-500/30'
              : 'bg-slate-900/60 border-slate-800 hover:border-slate-700'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Saudáveis</span>
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="mt-2 flex items-baseline space-x-2">
            <span className="text-2xl sm:text-3xl font-bold text-emerald-400 tracking-tight">
              {healthyCount}
            </span>
            <span className="text-xs text-slate-400">
              {total ? `${Math.round((healthyCount / total) * 100)}%` : '0%'}
            </span>
          </div>
        </div>

        {/* Degraded */}
        <div
          onClick={() => setStatusFilter('DEGRADED')}
          className={`cursor-pointer p-4 rounded-2xl border transition-all duration-150 ${
            statusFilter === 'DEGRADED'
              ? 'bg-amber-950/40 border-amber-500/60 ring-1 ring-amber-500/30'
              : 'bg-slate-900/60 border-slate-800 hover:border-slate-700'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Degradados</span>
            <AlertTriangle className="w-4 h-4 text-amber-400" />
          </div>
          <div className="mt-2 flex items-baseline space-x-2">
            <span className="text-2xl sm:text-3xl font-bold text-amber-400 tracking-tight">
              {degradedCount}
            </span>
            <span className="text-xs text-slate-400">em alerta</span>
          </div>
        </div>

        {/* Critical */}
        <div
          onClick={() => setStatusFilter('CRITICAL')}
          className={`cursor-pointer p-4 rounded-2xl border transition-all duration-150 ${
            statusFilter === 'CRITICAL'
              ? 'bg-rose-950/40 border-rose-500/60 ring-1 ring-rose-500/30'
              : 'bg-slate-900/60 border-slate-800 hover:border-slate-700'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Críticos</span>
            <ShieldAlert className="w-4 h-4 text-rose-400" />
          </div>
          <div className="mt-2 flex items-baseline space-x-2">
            <span className="text-2xl sm:text-3xl font-bold text-rose-400 tracking-tight">
              {criticalCount}
            </span>
            <span className="text-xs text-slate-400">ação imediata</span>
          </div>
        </div>

        {/* Offline */}
        <div
          onClick={() => setStatusFilter('OFFLINE')}
          className={`cursor-pointer p-4 rounded-2xl border transition-all duration-150 col-span-2 lg:col-span-1 ${
            statusFilter === 'OFFLINE'
              ? 'bg-slate-800/80 border-slate-400/60 ring-1 ring-slate-400/30'
              : 'bg-slate-900/60 border-slate-800 hover:border-slate-700'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Desconectados</span>
            <WifiOff className="w-4 h-4 text-slate-400" />
          </div>
          <div className="mt-2 flex items-baseline space-x-2">
            <span className="text-2xl sm:text-3xl font-bold text-slate-300 tracking-tight">
              {offlineCount}
            </span>
            <span className="text-xs text-slate-400">fila acumulando</span>
          </div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        {/* Search */}
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 text-slate-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Buscar por nome, device_id ou processador..."
            className="w-full pl-9 pr-4 py-2 rounded-xl bg-slate-900/80 border border-slate-800 text-xs text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
          />
        </div>

        {/* Filter Pills */}
        <div className="flex items-center space-x-1.5 overflow-x-auto pb-1 sm:pb-0 text-xs">
          {(['ALL', 'HEALTHY', 'DEGRADED', 'CRITICAL', 'OFFLINE'] as const).map((filter) => (
            <button
              key={filter}
              onClick={() => setStatusFilter(filter)}
              className={`px-3 py-1.5 rounded-lg font-medium whitespace-nowrap transition ${
                statusFilter === filter
                  ? 'bg-slate-800 text-white border border-slate-600 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/60'
              }`}
            >
              {filter === 'ALL' && 'Todos'}
              {filter === 'HEALTHY' && 'Saudáveis'}
              {filter === 'DEGRADED' && 'Degradados'}
              {filter === 'CRITICAL' && 'Críticos'}
              {filter === 'OFFLINE' && 'Offline'}
            </button>
          ))}
        </div>
      </div>

      {/* Devices Grid */}
      {isLoading ? (
        <div className="py-20 text-center">
          <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-xs text-slate-400">Carregando telemetria dos dispositivos...</p>
        </div>
      ) : filteredDevices.length === 0 ? (
        <div className="py-16 text-center bg-slate-900/40 rounded-2xl border border-slate-800">
          <Server className="w-10 h-10 text-slate-600 mx-auto mb-3" />
          <h4 className="text-sm font-semibold text-slate-300">Nenhum dispositivo encontrado</h4>
          <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">
            Nenhum dispositivo cadastrado corresponde aos filtros ativos ou à busca digitada.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredDevices.map((device) => {
            const status = device.latest?.status || 'HEALTHY'
            const netStatus = device.latest?.network_status || 'UNKNOWN'
            const isOffline = netStatus === 'OFFLINE'

            return (
              <div
                key={device.device_id}
                onClick={() => onSelectDevice(device.device_id)}
                className="group relative bg-slate-900/60 hover:bg-slate-900/90 border border-slate-800/80 hover:border-slate-700 rounded-2xl p-5 cursor-pointer transition-all duration-200 shadow-lg hover:shadow-indigo-500/5 hover:-translate-y-0.5 flex flex-col justify-between"
              >
                <div>
                  {/* Top Bar: Device Type & Status Badge */}
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center space-x-2.5">
                      <div className="p-2 rounded-xl bg-slate-800 border border-slate-700/60 text-slate-300 group-hover:text-white transition">
                        {device.device_name.toLowerCase().includes('laptop') ||
                        device.device_name.toLowerCase().includes('thinkpad') ? (
                          <Laptop className="w-4 h-4" />
                        ) : device.device_name.toLowerCase().includes('server') ? (
                          <Server className="w-4 h-4" />
                        ) : (
                          <Monitor className="w-4 h-4" />
                        )}
                      </div>
                      <div>
                        <h4 className="text-sm font-semibold text-white group-hover:text-indigo-300 transition tracking-tight">
                          {device.device_name}
                        </h4>
                        <div className="text-[11px] font-mono text-slate-400">
                          {device.device_id}
                        </div>
                      </div>
                    </div>

                    {/* Status Pill */}
                    <div className="flex flex-col items-end space-y-1">
                      <span
                        className={`inline-flex items-center space-x-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${
                          status === 'HEALTHY'
                            ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                            : status === 'DEGRADED'
                            ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                            : 'bg-rose-500/10 text-rose-300 border-rose-500/30'
                        }`}
                      >
                        <span
                          className={`w-1.5 h-1.5 rounded-full ${
                            status === 'HEALTHY'
                              ? 'bg-emerald-400'
                              : status === 'DEGRADED'
                              ? 'bg-amber-400'
                              : 'bg-rose-400'
                          }`}
                        />
                        <span>{status}</span>
                      </span>

                      {/* Network Pill */}
                      <span
                        className={`inline-flex items-center space-x-1 px-2 py-0.5 rounded-md text-[10px] font-medium ${
                          isOffline
                            ? 'bg-slate-800 text-rose-400 border border-rose-900/50'
                            : 'bg-slate-800/60 text-slate-400'
                        }`}
                      >
                        {isOffline ? <WifiOff className="w-2.5 h-2.5" /> : <Wifi className="w-2.5 h-2.5" />}
                        <span>{netStatus}</span>
                      </span>
                    </div>
                  </div>

                  {/* Hardware Specs Chips */}
                  <div className="space-y-1.5 my-3.5 py-2.5 border-y border-slate-800/60 text-xs">
                    <div className="flex items-center text-slate-400 truncate">
                      <Cpu className="w-3.5 h-3.5 mr-2 text-indigo-400 shrink-0" />
                      <span className="truncate">{device.hardware.cpu_model}</span>
                    </div>
                    <div className="flex items-center justify-between text-slate-400">
                      <span className="flex items-center">
                        <HardDrive className="w-3.5 h-3.5 mr-2 text-indigo-400 shrink-0" />
                        <span>RAM Total</span>
                      </span>
                      <span className="font-semibold text-slate-200">
                        {formatBytes(device.hardware.memory_total_bytes)}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Footer: Last Seen & Action */}
                <div className="flex items-center justify-between pt-2 text-xs text-slate-400">
                  <div className="flex items-center space-x-1.5">
                    <Clock className="w-3.5 h-3.5 text-slate-500" />
                    <span>{formatRelativeTime(device.last_seen_at)}</span>
                  </div>

                  <div className="flex items-center space-x-1 font-medium text-indigo-400 group-hover:text-indigo-300 group-hover:translate-x-0.5 transition-all">
                    <span>Ver detalhes</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
