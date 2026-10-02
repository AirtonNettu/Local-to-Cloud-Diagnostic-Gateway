"""Agent configuration loading and validation.

This package must not import ``agent.sync`` (enforced by the import-boundary
test): ``SyncSettings`` is defined here so the scan path never transitively
imports the HTTP client or the queue.
"""
