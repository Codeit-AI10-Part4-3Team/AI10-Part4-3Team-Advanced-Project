"""Independently deployable AI engine.

⚠️ Never import `api` or `backend_core` from here. The only coupling allowed between the
two apps is the HTTP contract in packages/contracts — a Python import across that line
silently destroys the "independently deployable AI module" property (AGENTS.md).

Pipeline direction is one-way: parsing -> chunking -> embedding -> retrieval -> generation.
"""
