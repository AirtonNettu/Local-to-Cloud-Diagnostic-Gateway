import type { ApiConfig, DeviceProfile, DiagnosticEvent } from '../types/diagnostic'
import { MOCK_DEVICES, MOCK_DIAGNOSTICS } from './mockData'

const DEFAULT_CONFIG: ApiConfig = {
  baseUrl: 'http://127.0.0.1:8000',
  readKey: 'local-read-key',
  isDemoMode: true, // Default to demo mode for instant visual gratification
}

export function loadStoredConfig(): ApiConfig {
  try {
    const raw = localStorage.getItem('diag_gateway_config')
    if (raw) {
      return { ...DEFAULT_CONFIG, ...JSON.parse(raw) }
    }
  } catch {
    // ignore localStorage errors
  }
  return DEFAULT_CONFIG
}

export function saveStoredConfig(config: ApiConfig): void {
  try {
    localStorage.setItem('diag_gateway_config', JSON.stringify(config))
  } catch {
    // ignore localStorage errors
  }
}

async function request<T>(
  config: ApiConfig,
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const cleanBase = config.baseUrl.replace(/\/+$/, '')
  const cleanPath = path.startsWith('/') ? path : `/${path}`
  const url = `${cleanBase}${cleanPath}`

  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(config.readKey ? { Authorization: `Bearer ${config.readKey}` } : {}),
    ...(options.headers as Record<string, string> | undefined),
  }

  const response = await fetch(url, {
    ...options,
    headers,
  })

  if (!response.ok) {
    let errMessage = `HTTP ${response.status}: ${response.statusText}`
    try {
      const errJson = await response.json()
      if (errJson?.error?.message) {
        errMessage = `${errJson.error.code ? `[${errJson.error.code}] ` : ''}${errJson.error.message}`
      }
    } catch {
      // not json
    }
    throw new Error(errMessage)
  }

  return response.json()
}

export async function fetchHealth(config: ApiConfig): Promise<{ status: string; service: string }> {
  if (config.isDemoMode) {
    return { status: 'ok', service: 'diagnostic-gateway (demo)' }
  }
  return request<{ status: string; service: string }>(config, '/health')
}

export async function fetchDevices(
  config: ApiConfig,
  limit = 50,
  cursor?: string | null
): Promise<{ items: DeviceProfile[]; next_cursor: string | null }> {
  if (config.isDemoMode) {
    return { items: MOCK_DEVICES, next_cursor: null }
  }

  const params = new URLSearchParams()
  params.set('limit', String(limit))
  if (cursor) {
    params.set('cursor', cursor)
  }

  return request<{ items: DeviceProfile[]; next_cursor: string | null }>(
    config,
    `/v1/devices?${params.toString()}`
  )
}

export async function fetchDevice(
  config: ApiConfig,
  deviceId: string
): Promise<DeviceProfile> {
  if (config.isDemoMode) {
    const found = MOCK_DEVICES.find((d) => d.device_id === deviceId)
    if (!found) throw new Error(`Dispositivo não encontrado: ${deviceId}`)
    return found
  }

  return request<DeviceProfile>(config, `/v1/devices/${encodeURIComponent(deviceId)}`)
}

export async function fetchDiagnostics(
  config: ApiConfig,
  deviceId: string,
  limit = 20,
  cursor?: string | null
): Promise<{ device_id: string; items: DiagnosticEvent[]; next_cursor: string | null }> {
  if (config.isDemoMode) {
    const items = MOCK_DIAGNOSTICS[deviceId] || []
    return {
      device_id: deviceId,
      items,
      next_cursor: null,
    }
  }

  const params = new URLSearchParams()
  params.set('limit', String(limit))
  if (cursor) {
    params.set('cursor', cursor)
  }

  return request<{ device_id: string; items: DiagnosticEvent[]; next_cursor: string | null }>(
    config,
    `/v1/devices/${encodeURIComponent(deviceId)}/diagnostics?${params.toString()}`
  )
}
