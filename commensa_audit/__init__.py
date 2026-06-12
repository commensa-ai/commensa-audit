"""commensa-audit — repo in, one-page AI Rework Report out.

Architecture rule (SPEC.md): extractors and the engine are separate. The
engine consumes units.csv (one row per unit of work), never a host API.
Any future host (Gitea first) is one new extractor emitting the same CSV.
"""

__version__ = "0.2.1"
