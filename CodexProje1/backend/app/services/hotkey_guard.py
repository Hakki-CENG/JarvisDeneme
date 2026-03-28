from __future__ import annotations

import threading

from app.services.safety_service import safety_service


class HotkeyGuard:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> str:
        if self._running:
            return 'already_running'

        try:
            import keyboard  # type: ignore
        except Exception:
            return 'keyboard_package_missing'

        self._running = True

        def worker() -> None:
            keyboard.add_hotkey('ctrl+shift+f12', lambda: safety_service.trigger_emergency_stop('Global hotkey'))
            keyboard.wait()

        self._thread = threading.Thread(target=worker, name='hotkey-guard', daemon=True)
        self._thread.start()
        return 'started'


hotkey_guard = HotkeyGuard()
