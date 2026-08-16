"""Persistence only: tables and queries, no business rules.

Every function takes the cursor as its first argument and never opens one —
the caller owns the transaction lifecycle.
"""
