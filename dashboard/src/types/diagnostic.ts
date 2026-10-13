export interface DeviceOS {
  name: string
  version: string
  architecture: string
}

export interface DeviceHardware {
  cpu_model: string
  logical_cpus: number
  physical_cores: number
  memory_total_bytes: number
}

export interface LatestEventSummary {
  event_id: string
  timestamp: string
  status: 'HEALTHY' | 'DEGRADED' | 'CRITICAL'
  network_status: 'HEALTHY' | 'DEGRADED' | 'UNSTABLE' | 'OFFLINE' | 'UNKNOWN'
  alert_count: number
}

export interface DeviceProfile {
  device_id: string
  device_name: string
  os: DeviceOS
  hardware: DeviceHardware
  agent_version: string
  registered_at: string
  updated_at: string
  last_seen_at?: string
  latest?: LatestEventSummary | null
}

export interface DiagnosticCheck {
  name: string
  status: 'PASS' | 'WARN' | 'FAIL' | 'SKIP'
  summary: string
  evidence?: Record<string, unknown>
}

export interface DiagnosticAlert {
  rule_id: string
  severity: 'INFO' | 'WARNING' | 'CRITICAL'
  message: string
  subject?: string
}

export interface DiagnosticMetric {
  name: string
  value: number
  unit: string
  labels?: Record<string, string>
}

export interface DiagnosticEvent {
  event_id: string
  timestamp: string
  received_at: string
  source: string
  status: 'HEALTHY' | 'DEGRADED' | 'CRITICAL'
  network_status: 'HEALTHY' | 'DEGRADED' | 'UNSTABLE' | 'OFFLINE' | 'UNKNOWN'
  alert_count: number
  checks: DiagnosticCheck[]
  alerts: DiagnosticAlert[]
  metrics: DiagnosticMetric[]
}

export interface DevicesResponse {
  items: DeviceProfile[]
  next_cursor: string | null
}

export interface DiagnosticsResponse {
  device_id: string
  items: DiagnosticEvent[]
  next_cursor: string | null
}

export interface ApiConfig {
  baseUrl: string
  readKey: string
  isDemoMode: boolean
}
