import type { DeviceProfile, DiagnosticEvent } from '../types/diagnostic'

export const MOCK_DEVICES: DeviceProfile[] = [
  {
    device_id: 'workstation-dev-01',
    device_name: 'Dell Precision Workstation',
    os: {
      name: 'Windows',
      version: '10.0.22631 (Build 22631.3007)',
      architecture: 'AMD64',
    },
    hardware: {
      cpu_model: 'AMD Ryzen 9 7950X 16-Core Processor',
      logical_cpus: 32,
      physical_cores: 16,
      memory_total_bytes: 68719476736, // 64 GB
    },
    agent_version: '0.1.0',
    registered_at: '2026-02-15T08:00:00.000Z',
    updated_at: '2026-03-01T14:22:10.000Z',
    last_seen_at: '2026-03-01T14:22:10.000Z',
    latest: {
      event_id: '018f-demo-healthy-001',
      timestamp: '2026-03-01T14:22:10.000Z',
      status: 'HEALTHY',
      network_status: 'HEALTHY',
      alert_count: 0,
    },
  },
  {
    device_id: 'laptop-sales-04',
    device_name: 'Lenovo ThinkPad T14',
    os: {
      name: 'Windows',
      version: '10.0.22621 (Build 22621.2861)',
      architecture: 'AMD64',
    },
    hardware: {
      cpu_model: '13th Gen Intel(R) Core(TM) i7-1365U',
      logical_cpus: 12,
      physical_cores: 10,
      memory_total_bytes: 17179869184, // 16 GB
    },
    agent_version: '0.1.0',
    registered_at: '2026-01-20T10:15:00.000Z',
    updated_at: '2026-03-01T14:20:05.000Z',
    last_seen_at: '2026-03-01T14:20:05.000Z',
    latest: {
      event_id: '018f-demo-degraded-net',
      timestamp: '2026-03-01T14:20:05.000Z',
      status: 'DEGRADED',
      network_status: 'DEGRADED',
      alert_count: 2,
    },
  },
  {
    device_id: 'server-edge-storage-02',
    device_name: 'Edge Gateway Node 02',
    os: {
      name: 'Windows',
      version: '10.0.20348 (Server 2022)',
      architecture: 'AMD64',
    },
    hardware: {
      cpu_model: 'Intel(R) Xeon(R) Silver 4314 CPU @ 2.40GHz',
      logical_cpus: 32,
      physical_cores: 16,
      memory_total_bytes: 34359738368, // 32 GB
    },
    agent_version: '0.1.0',
    registered_at: '2026-02-01T11:00:00.000Z',
    updated_at: '2026-03-01T14:15:30.000Z',
    last_seen_at: '2026-03-01T14:15:30.000Z',
    latest: {
      event_id: '018f-demo-low-disk',
      timestamp: '2026-03-01T14:15:30.000Z',
      status: 'CRITICAL',
      network_status: 'HEALTHY',
      alert_count: 1,
    },
  },
  {
    device_id: 'pos-terminal-store-09',
    device_name: 'HP Engage POS Terminal',
    os: {
      name: 'Windows',
      version: '10.0.19045 (Windows 10 IoT Enterprise)',
      architecture: 'AMD64',
    },
    hardware: {
      cpu_model: 'Intel(R) Core(TM) i3-10100E CPU @ 3.20GHz',
      logical_cpus: 8,
      physical_cores: 4,
      memory_total_bytes: 8589934592, // 8 GB
    },
    agent_version: '0.1.0',
    registered_at: '2026-02-10T09:30:00.000Z',
    updated_at: '2026-03-01T13:45:00.000Z',
    last_seen_at: '2026-03-01T13:45:00.000Z',
    latest: {
      event_id: '018f-demo-high-mem',
      timestamp: '2026-03-01T13:45:00.000Z',
      status: 'DEGRADED',
      network_status: 'HEALTHY',
      alert_count: 1,
    },
  },
  {
    device_id: 'branch-office-kiosk-01',
    device_name: 'Branch Kiosk Display',
    os: {
      name: 'Windows',
      version: '10.0.22631',
      architecture: 'AMD64',
    },
    hardware: {
      cpu_model: 'Intel(R) Celeron(R) N5105 @ 2.00GHz',
      logical_cpus: 4,
      physical_cores: 4,
      memory_total_bytes: 8589934592,
    },
    agent_version: '0.1.0',
    registered_at: '2026-01-05T12:00:00.000Z',
    updated_at: '2026-03-01T10:00:00.000Z',
    last_seen_at: '2026-03-01T10:00:00.000Z',
    latest: {
      event_id: '018f-demo-offline',
      timestamp: '2026-03-01T10:00:00.000Z',
      status: 'DEGRADED',
      network_status: 'OFFLINE',
      alert_count: 2,
    },
  },
]

export const MOCK_DIAGNOSTICS: Record<string, DiagnosticEvent[]> = {
  'workstation-dev-01': [
    {
      event_id: '018f-demo-healthy-001',
      timestamp: '2026-03-01T14:22:10.000Z',
      received_at: '2026-03-01T14:22:12.000Z',
      source: 'live',
      status: 'HEALTHY',
      network_status: 'HEALTHY',
      alert_count: 0,
      checks: [
        {
          name: 'cpu.utilization',
          status: 'PASS',
          summary: 'CPU usage is normal (18.4%)',
          evidence: { current_percent: 18.4, threshold_warning: 90.0 },
        },
        {
          name: 'memory.utilization',
          status: 'PASS',
          summary: 'Memory usage is normal (34.2% of 64 GB)',
          evidence: { current_percent: 34.2, used_bytes: 23502621081 },
        },
        {
          name: 'storage.disk_space',
          status: 'PASS',
          summary: 'Drive C: space is healthy (42.8% used)',
          evidence: { drive: 'C:', used_percent: 42.8, free_gb: 512.4 },
        },
        {
          name: 'network.gateway_connectivity',
          status: 'PASS',
          summary: 'Default gateway responds with low latency (1.4 ms)',
          evidence: { gateway_ip: '<ip>', latency_ms: 1.4 },
        },
        {
          name: 'network.dns_resolution',
          status: 'PASS',
          summary: 'All configured test hostnames resolved successfully',
          evidence: { tested: ['aws.amazon.com', 'example.com'], avg_latency_ms: 14.2 },
        },
        {
          name: 'network.internet_probes',
          status: 'PASS',
          summary: 'Internet probes successful (0% loss, avg 12.8 ms)',
          evidence: { loss_percent: 0.0, avg_latency_ms: 12.8 },
        },
      ],
      alerts: [],
      metrics: [
        { name: 'cpu_percent', value: 18.4, unit: 'percent' },
        { name: 'memory_percent', value: 34.2, unit: 'percent' },
        { name: 'memory_used_bytes', value: 23502621081, unit: 'bytes' },
        { name: 'storage_used_percent', value: 42.8, unit: 'percent' },
        { name: 'network_latency_ms', value: 12.8, unit: 'ms' },
        { name: 'packet_loss_percent', value: 0.0, unit: 'percent' },
      ],
    },
  ],
  'laptop-sales-04': [
    {
      event_id: '018f-demo-degraded-net',
      timestamp: '2026-03-01T14:20:05.000Z',
      received_at: '2026-03-01T14:20:10.000Z',
      source: 'live',
      status: 'DEGRADED',
      network_status: 'DEGRADED',
      alert_count: 2,
      checks: [
        {
          name: 'cpu.utilization',
          status: 'PASS',
          summary: 'CPU usage is normal (24.1%)',
          evidence: { current_percent: 24.1 },
        },
        {
          name: 'memory.utilization',
          status: 'PASS',
          summary: 'Memory usage normal (58.4%)',
          evidence: { current_percent: 58.4 },
        },
        {
          name: 'network.gateway_connectivity',
          status: 'WARN',
          summary: 'Gateway latency elevated (84.2 ms)',
          evidence: { gateway_ip: '<ip>', latency_ms: 84.2 },
        },
        {
          name: 'network.internet_probes',
          status: 'WARN',
          summary: 'Elevated packet loss (25.0%) and high latency (210.4 ms)',
          evidence: { loss_percent: 25.0, avg_latency_ms: 210.4 },
        },
      ],
      alerts: [
        {
          rule_id: 'RULE_NETWORK_HIGH_LATENCY',
          severity: 'WARNING',
          message: 'Internet round-trip latency exceeded warning threshold (210 ms > 150 ms)',
          subject: 'network',
        },
        {
          rule_id: 'RULE_NETWORK_PACKET_LOSS',
          severity: 'WARNING',
          message: 'Probe packet loss is 25.0% (threshold: 10.0%)',
          subject: 'network',
        },
      ],
      metrics: [
        { name: 'cpu_percent', value: 24.1, unit: 'percent' },
        { name: 'memory_percent', value: 58.4, unit: 'percent' },
        { name: 'storage_used_percent', value: 71.0, unit: 'percent' },
        { name: 'network_latency_ms', value: 210.4, unit: 'ms' },
        { name: 'packet_loss_percent', value: 25.0, unit: 'percent' },
      ],
    },
  ],
  'server-edge-storage-02': [
    {
      event_id: '018f-demo-low-disk',
      timestamp: '2026-03-01T14:15:30.000Z',
      received_at: '2026-03-01T14:15:32.000Z',
      source: 'live',
      status: 'CRITICAL',
      network_status: 'HEALTHY',
      alert_count: 1,
      checks: [
        {
          name: 'storage.disk_space',
          status: 'FAIL',
          summary: 'Drive C: reached critical capacity (96.4% used, only 7.2 GB remaining)',
          evidence: { drive: 'C:', used_percent: 96.4, free_gb: 7.2 },
        },
        {
          name: 'cpu.utilization',
          status: 'PASS',
          summary: 'CPU usage is normal (12.0%)',
          evidence: { current_percent: 12.0 },
        },
      ],
      alerts: [
        {
          rule_id: 'RULE_STORAGE_CRITICAL',
          severity: 'CRITICAL',
          message: 'Primary volume C: usage is 96.4%, exceeding critical threshold of 95.0%',
          subject: 'storage',
        },
      ],
      metrics: [
        { name: 'cpu_percent', value: 12.0, unit: 'percent' },
        { name: 'memory_percent', value: 41.5, unit: 'percent' },
        { name: 'storage_used_percent', value: 96.4, unit: 'percent' },
        { name: 'network_latency_ms', value: 8.5, unit: 'ms' },
        { name: 'packet_loss_percent', value: 0.0, unit: 'percent' },
      ],
    },
  ],
  'pos-terminal-store-09': [
    {
      event_id: '018f-demo-high-mem',
      timestamp: '2026-03-01T13:45:00.000Z',
      received_at: '2026-03-01T13:45:02.000Z',
      source: 'live',
      status: 'DEGRADED',
      network_status: 'HEALTHY',
      alert_count: 1,
      checks: [
        {
          name: 'memory.utilization',
          status: 'WARN',
          summary: 'Memory pressure warning (91.2% used of 8 GB)',
          evidence: { current_percent: 91.2, free_mb: 752 },
        },
      ],
      alerts: [
        {
          rule_id: 'RULE_MEMORY_WARNING',
          severity: 'WARNING',
          message: 'Physical memory utilization is 91.2% (warning threshold: 90.0%)',
          subject: 'memory',
        },
      ],
      metrics: [
        { name: 'cpu_percent', value: 45.0, unit: 'percent' },
        { name: 'memory_percent', value: 91.2, unit: 'percent' },
        { name: 'storage_used_percent', value: 54.0, unit: 'percent' },
        { name: 'network_latency_ms', value: 15.0, unit: 'ms' },
      ],
    },
  ],
  'branch-office-kiosk-01': [
    {
      event_id: '018f-demo-offline',
      timestamp: '2026-03-01T10:00:00.000Z',
      received_at: '2026-03-01T10:00:05.000Z',
      source: 'live',
      status: 'DEGRADED',
      network_status: 'OFFLINE',
      alert_count: 2,
      checks: [
        {
          name: 'network.gateway_connectivity',
          status: 'PASS',
          summary: 'Local gateway reachable',
          evidence: { gateway_ip: '<ip>', latency_ms: 2.1 },
        },
        {
          name: 'network.internet_probes',
          status: 'FAIL',
          summary: 'All external probes timed out (100% loss)',
          evidence: { loss_percent: 100.0 },
        },
      ],
      alerts: [
        {
          rule_id: 'RULE_NETWORK_OFFLINE',
          severity: 'WARNING',
          message: 'Host is completely offline: external internet destinations unreachable',
          subject: 'network',
        },
      ],
      metrics: [
        { name: 'cpu_percent', value: 8.5, unit: 'percent' },
        { name: 'memory_percent', value: 38.0, unit: 'percent' },
        { name: 'storage_used_percent', value: 28.0, unit: 'percent' },
        { name: 'packet_loss_percent', value: 100.0, unit: 'percent' },
      ],
    },
  ],
}
