"""Monthly Report Automation.

Pipeline: English .docx inspection reports -> filter by inspection month ->
extract evolving text fields (images ignored) -> translate to Azerbaijani via an
authoritative JSON dictionary -> merge -> render a print-ready PDF.

This package is currently scaffolding: modules define their responsibilities and
I/O contracts but do not yet implement behavior. See architecture/ADR-001.
"""

__version__ = "0.1.0"
