"""HTTP layer.

Routers stay thin: validate request -> call backend_core -> map response.
Business logic in a router is a design defect, not a style nit (AGENTS.md).
"""
