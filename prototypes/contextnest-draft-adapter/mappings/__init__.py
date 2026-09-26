"""Cross-draft mappings for Context Nest (see MAPPING.md).

- mappings.ibm      : node <-> IBM MemoryRecord, using the IBM prototype's own classes
- mappings.packer   : vault <-> Packer memory directory, checked by python-loader-validator
- mappings.cognee   : the Cognee six-part core as a declarative table, per-node view,
                      manifest and receipt (no cognee or COGX dependency)
- mappings.aidp     : node <-> FMP files / inferences, and which /fmp endpoints fit
- mappings.exchange : Manifest and Receipt shapes shared by all of the above

Every module has an UNMAPPABLE table. Version numbers, hashes, checkpoints and status
transitions are always read from or written by the `ctx` CLI; the mappings only move
fields between shapes.
"""

from mappings._nest import NestIO, Node, VersionEntry
from mappings.exchange import Manifest, Receipt

__all__ = ["Manifest", "NestIO", "Node", "Receipt", "VersionEntry"]
