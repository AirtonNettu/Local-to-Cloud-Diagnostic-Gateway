import { useEffect, useState, useCallback } from 'react'
import type { ApiConfig, DeviceProfile, DiagnosticEvent } from './types/diagnostic'
import {
  fetchDevices,
  fetchDiagnostics,
  fetchHealth,
  loadStoredConfig,
  saveStoredConfig,
} from './services/api'
import { Header } from './components/Header'
import { FleetOverview } from './components/FleetOverview'
import { DeviceDetail } from './components/DeviceDetail'
import { ConfigModal } from './components/ConfigModal'
import { AlertCircle } from 'lucide-react'

export function App() {
  const [config, setConfig] = useState<ApiConfig>(loadStoredConfig)
  const [devices, setDevices] = useState<DeviceProfile[]>([])
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null)
  const [diagnostics, setDiagnostics] = useState<DiagnosticEvent[]>([])
  const [isLoadingDevices, setIsLoadingDevices] = useState(false)
  const [isLoadingDiagnostics, setIsLoadingDiagnostics] = useState(false)
  const [connectionHealthy, setConnectionHealthy] = useState<boolean | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [isConfigModalOpen, setIsConfigModalOpen] = useState(false)

  // Save config changes to localStorage
  const handleConfigChange = (newConfig: ApiConfig) => {
    setConfig(newConfig)
    saveStoredConfig(newConfig)
  }

  // Load devices list
  const loadFleet = useCallback(async () => {
    setIsLoadingDevices(true)
    setErrorMessage(null)
    try {
      // Test health
      const health = await fetchHealth(config)
      setConnectionHealthy(health.status === 'ok')

      // Fetch devices
      const res = await fetchDevices(config)
      setDevices(res.items)
    } catch (err) {
      setConnectionHealthy(false)
      setErrorMessage(
        err instanceof Error
          ? err.message
          : 'Não foi possível carregar a lista de dispositivos.'
      )
    } finally {
      setIsLoadingDevices(false)
    }
  }, [config])

  // Load diagnostics when a device is selected
  const loadDeviceDiagnostics = useCallback(
    async (deviceId: string) => {
      setIsLoadingDiagnostics(true)
      try {
        const res = await fetchDiagnostics(config, deviceId)
        setDiagnostics(res.items)
      } catch (err) {
        console.error('Falha ao carregar diagnósticos:', err)
      } finally {
        setIsLoadingDiagnostics(false)
      }
    },
    [config]
  )

  // Effect to reload fleet on config changes
  useEffect(() => {
    loadFleet()
  }, [loadFleet])

  // Effect when selected device changes
  useEffect(() => {
    if (selectedDeviceId) {
      loadDeviceDiagnostics(selectedDeviceId)
    } else {
      setDiagnostics([])
    }
  }, [selectedDeviceId, loadDeviceDiagnostics])

  const selectedDevice = devices.find((d) => d.device_id === selectedDeviceId) || null

  return (
    <div className="min-h-screen bg-[#0b0f17] text-slate-100 flex flex-col font-sans">
      <Header
        config={config}
        onConfigChange={handleConfigChange}
        onOpenSettings={() => setIsConfigModalOpen(true)}
        onRefresh={() => {
          loadFleet()
          if (selectedDeviceId) loadDeviceDiagnostics(selectedDeviceId)
        }}
        isLoading={isLoadingDevices || isLoadingDiagnostics}
        connectionHealthy={connectionHealthy}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Error Notification Banner */}
        {errorMessage && !config.isDemoMode && (
          <div className="mb-6 p-4 rounded-2xl bg-rose-950/40 border border-rose-800/80 text-rose-200 text-xs flex items-center justify-between shadow-lg">
            <div className="flex items-center space-x-2.5">
              <AlertCircle className="w-5 h-5 text-rose-400 shrink-0" />
              <span>
                <strong>Erro de Conexão:</strong> {errorMessage}
              </span>
            </div>
            <button
              onClick={() => setIsConfigModalOpen(true)}
              className="px-3 py-1 rounded-lg bg-rose-900/60 hover:bg-rose-800 text-xs font-semibold text-rose-100 transition ml-3"
            >
              Configurar Conexão
            </button>
          </div>
        )}

        {/* View Switcher */}
        {selectedDevice ? (
          <DeviceDetail
            device={selectedDevice}
            diagnostics={diagnostics}
            isLoadingDiagnostics={isLoadingDiagnostics}
            onBack={() => setSelectedDeviceId(null)}
          />
        ) : (
          <FleetOverview
            devices={devices}
            onSelectDevice={(id) => setSelectedDeviceId(id)}
            isLoading={isLoadingDevices}
          />
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-900/80 py-6 text-center text-xs text-slate-500">
        <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-2">
          <span>Local-to-Cloud Diagnostic Gateway • Edge Computing & Serverless Observability</span>
          <span className="font-mono text-[11px] text-slate-600">
            {config.isDemoMode ? 'Modo de Teste Local' : `Conectado a ${config.baseUrl}`}
          </span>
        </div>
      </footer>

      {/* Connection Config Modal */}
      <ConfigModal
        isOpen={isConfigModalOpen}
        onClose={() => setIsConfigModalOpen(false)}
        config={config}
        onSave={handleConfigChange}
      />
    </div>
  )
}

export default App
