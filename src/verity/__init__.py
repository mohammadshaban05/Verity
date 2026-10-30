"""Verity: verify claims against cited, verifiable evidence.

The pipeline runs in stages: corpus -> passages -> retrieval -> judge -> citation
verifier -> report. Each stage is a plain function with typed inputs and outputs.
See docs/DECISIONS.md for the rationale.
"""

__version__ = "0.0.1"
