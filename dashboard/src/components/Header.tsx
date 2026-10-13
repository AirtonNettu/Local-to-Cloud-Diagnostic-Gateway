import React from 'react'
import {
  Activity,
  Cloud,
  HardDrive,
  RefreshCw,
  Settings,
  Sparkles,
} from 'lucide-react'
import type { ApiConfig } from '../types/diagnostic'

interface HeaderProps {
  config: ApiConfig
  onConfigChange: (newConfig: ApiConfig) => void
  onOpenSettings: () => void
  onRefresh: () => void
  isLoading: boolean
  connectionHealthy: boolean | null
}

export const Header: React.FC<HeaderProps> = ({
  config,
  onConfigChange,
  onOpenSettings,
  onRefresh,
  isLoading,
  connectionHealthy,
}) => {
  return (
    <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur-md sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand */}
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-600 via-indigo-600 to-violet-600 flex items-center justify-center shadow-lg shadow-indigo-500/20 ring-1 ring-white/20">
            <Activity className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="font-bold text-lg tracking-tight text-white">
                Diagnostic Gateway
              </span>
              <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-slate-800 text-slate-300 border border-slate-700">
                v0.1.0
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Edge-First & Serverless Telemetry Observatory
            </p>
          </div>
        </div>

        {/* Status & Controls */}
        <div className="flex items-center space-x-3">
          {/* Demo Mode Toggle Button */}
          <button
            onClick={() => {
              const updated = { ...config, isDemoMode: !config.isDemoMode }
              onConfigChange(updated)
            }}
            className={`flex items-center space-x-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              config.isDemoMode
                ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30 shadow-sm shadow-amber-500/10'
                : 'bg-slate-800/80 text-slate-400 hover:text-slate-200 border border-slate-700/60'
            }`}
            title="Alternar entre dados simulados (Demo) e API real"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>{config.isDemoMode ? 'Modo Demo Ativo' : 'Modo Live'}</span>
          </button>

          {/* Connection Pill */}
          <div
            className={`hidden sm:flex items-center space-x-2 px-3 py-1.5 rounded-lg text-xs font-medium border ${
              config.isDemoMode
                ? 'bg-indigo-950/40 text-indigo-300 border-indigo-800/50'
                : connectionHealthy
                ? 'bg-emerald-950/40 text-emerald-300 border-emerald-800/50'
                : 'bg-rose-950/40 text-rose-300 border-rose-800/50'
            }`}
          >
            {config.isDemoMode ? (
              <HardDrive className="w-3.5 h-3.5 text-indigo-400" />
            ) : (
              <Cloud className="w-3.5 h-3.5" />
            )}
            <span>
              {config.isDemoMode
                ? 'Simulador Local'
                : connectionHealthy
                ? 'API Conectada'
                : 'API Inacessível'}
            </span>
            <span
              className={`w-2 h-2 rounded-full ${
                config.isDemoMode
                  ? 'bg-indigo-400'
                  : connectionHealthy
                  ? 'bg-emerald-400 animate-pulse'
                  : 'bg-rose-400'
              }`}
            />
          </div>

          {/* Refresh Button */}
          <button
            onClick={onRefresh}
            disabled={isLoading}
            className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700/80 text-slate-300 hover:text-white border border-slate-700 transition disabled:opacity-50"
            title="Atualizar dados"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </button>

          {/* Settings Button */}
          <button
            onClick={onOpenSettings}
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-md shadow-indigo-600/30 transition"
          >
            <Settings className="w-4 h-4" />
            <span className="hidden md:inline">Conexão</span>
          </button>
        </div>
      </div>
    </header>
  )
}
