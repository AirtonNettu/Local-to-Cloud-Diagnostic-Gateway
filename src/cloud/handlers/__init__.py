"""Lambda entry points: one function per resource group (design B.14).

Four handlers (``health``, ``device``, ``telemetry``, ``diagnostic``) group the
routes by resource so read-only functions keep read-only IAM. Each module owns
its ``REQUIRED_ENV`` and builds its dependencies lazily on first invocation.
"""
