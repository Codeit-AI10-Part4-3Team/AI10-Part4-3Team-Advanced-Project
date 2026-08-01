"""Domain layer.

⚠️ Must never import `api`. Domain logic stays runnable and testable without FastAPI —
that is what lets the eval/analysis tooling call it directly.
"""
