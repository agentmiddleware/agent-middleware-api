"""API schema package.

Imports are per-file by convention (``from app.schemas.billing import ...``),
not through this package: schema modules import from each other (trust pulls
in policies, pods pulls in billing) and from ``app.core``, so re-exporting
everything here would invite import cycles for no runtime benefit. Import
names from their defining module.
"""
