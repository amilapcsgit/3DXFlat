from __future__ import annotations

from PySide6.QtGui import QSurfaceFormat


def _configure_default_surface() -> None:
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setVersion(4, 1)
    QSurfaceFormat.setDefaultFormat(fmt)


def run_qt_app() -> int:
    _configure_default_surface()
    from qt_app.main_window import run_qt_app as _run_qt_app

    return int(_run_qt_app())
