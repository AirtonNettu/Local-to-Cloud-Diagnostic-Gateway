"""Hand-written payload validators: the API contract shared by both sides.

The cloud enforces these rules on every request; the agent pre-checks every
outgoing event with the same code, so a contract test proves the agent's output
is always acceptable to the backend.
"""
