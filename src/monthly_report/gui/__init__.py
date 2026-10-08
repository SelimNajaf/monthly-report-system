"""Desktop dashboard frontend for the Monthly Report pipeline.

A presentation layer, nothing more. It launches the existing entry points
(``main.py``, ``uploader.py``) as child processes, streams their stdout into a
console widget, and visualises the artifacts they leave on disk.

Dependencies point strictly inward::

    ui/  ->  services/  ->  monthly_report.* (the backend)

``services`` may import ``QtCore`` (signals, QProcess) but never ``QtWidgets``;
``ui`` never touches the backend directly. Nothing in the backend imports this
package, so the whole directory can be deleted without breaking the pipeline.
"""

__all__ = ["__version__"]

__version__ = "1.0.0"
