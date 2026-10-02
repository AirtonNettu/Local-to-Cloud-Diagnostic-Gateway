"""Shared, stdlib-only code used by both the agent and the cloud backend.

This package holds the data models, payload validators (the API contract) and
utility helpers (IDs, time, JSON logging). It must not import anything outside
the standard library so that both the Windows agent and the AWS Lambda bundle
can depend on it without pulling in extra dependencies.
"""
