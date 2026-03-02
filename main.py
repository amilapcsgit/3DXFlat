import os
import sys


def _set_windows_app_user_model_id() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        app_id = "3DXFlat.Advanced.Desktop"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        # Best-effort branding; failures should not block startup.
        pass


def run_tk_fallback() -> None:
    try:
        from gui import FlattenApp
    except Exception as exc:
        raise RuntimeError(
            "Tk fallback is unavailable. Install tkinter support or run Qt mode only."
        ) from exc

    app = FlattenApp()
    app.mainloop()


def run_default_app() -> int:
    force_tk = os.environ.get("THREEDXFLAT_FORCE_TK", "").strip() == "1"
    force_qt = os.environ.get("THREEDXFLAT_FORCE_QT", "").strip() == "1"

    if force_tk and force_qt:
        print("[3DXFlat] THREEDXFLAT_FORCE_QT is ignored because THREEDXFLAT_FORCE_TK=1.")

    if force_tk:
        run_tk_fallback()
        return 0

    try:
        from qt_app.main import run_qt_app

        return int(run_qt_app())
    except Exception as exc:
        if force_qt:
            print(f"[3DXFlat] Qt launch failed in force mode: {exc}")
            return 1
        print(f"[3DXFlat] Qt launch failed, falling back to Tkinter: {exc}")
        try:
            run_tk_fallback()
            return 0
        except Exception as tk_exc:
            print(f"[3DXFlat] Tk fallback failed: {tk_exc}")
            return 1


if __name__ == "__main__":
    _set_windows_app_user_model_id()
    raise SystemExit(run_default_app())
