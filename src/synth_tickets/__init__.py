"""Synthetic Contoso / M365-style support ticket dataset for the POC.

See `generator.py` for the public API and `load_synth_tickets_to_fabric.py`
for the CLI that writes the resulting Delta table to OneLake.
"""

from .generator import generate_tickets

__all__ = ["generate_tickets"]
