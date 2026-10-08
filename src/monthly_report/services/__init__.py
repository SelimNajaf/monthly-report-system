"""Headless pipeline services (no GUI dependency).

Distinct from :mod:`monthly_report.gui.services`, which back the desktop
dashboard. Modules here are used by the unattended ``main.py`` pipeline — e.g.
``network_ingestion`` stages fresh reports off the LAN share before a run.
"""
