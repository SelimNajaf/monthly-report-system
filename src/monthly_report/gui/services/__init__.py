"""Service layer: everything the UI needs that is not a widget.

Modules here may import ``QtCore`` for signals and ``QProcess``, but must never
import ``QtWidgets`` — that keeps them testable in a headless CI run. The two
parsers (``progress``, ``ansi``) import no Qt at all and touch no disk.
"""
