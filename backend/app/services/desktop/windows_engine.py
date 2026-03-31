from __future__ import annotations

import asyncio
import platform
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

import httpx

from app.core.settings import settings
from app.models.schemas import ActionEnvelope, ActionResult, ActionType
from app.services.audit_service import audit_service
from app.services.desktop.base import DesktopEngine, SimulatedDesktopEngine, ensure_directory
from app.services.policy_service import policy_service


class WindowsDesktopEngine(DesktopEngine):
    def __init__(self) -> None:
        self._pyautogui = None
        self._pyperclip = None
        try:
            import pyautogui

            pyautogui.FAILSAFE = True
            self._pyautogui = pyautogui
        except Exception:
            self._pyautogui = None
        try:
            import pyperclip

            self._pyperclip = pyperclip
        except Exception:
            self._pyperclip = None

    async def execute(self, action: ActionEnvelope) -> ActionResult:
        try:
            if len(str(action.parameters)) > settings.max_action_payload_chars:
                return ActionResult(action_id=action.id, success=False, error='Action payload exceeds max_action_payload_chars')
            if action.action == ActionType.move_mouse:
                return self._move_mouse(action)
            if action.action == ActionType.click:
                return self._click(action)
            if action.action == ActionType.type_text:
                return self._type_text(action)
            if action.action == ActionType.hotkey:
                return self._hotkey(action)
            if action.action == ActionType.wait:
                return await self._wait(action)
            if action.action == ActionType.open_app:
                return self._open_app(action)
            if action.action == ActionType.focus_window:
                return self._focus_window(action)
            if action.action == ActionType.read_screen:
                return self._read_screen(action)
            if action.action == ActionType.file_ops:
                return self._file_ops(action)
            if action.action == ActionType.shell_exec:
                return await self._shell_exec(action)
            if action.action == ActionType.browser_script:
                return await self._browser_script(action)
            if action.action == ActionType.http_request:
                return await self._http_request(action)
            if action.action == ActionType.clipboard_read:
                return self._clipboard_read(action)
            if action.action == ActionType.clipboard_write:
                return self._clipboard_write(action)
            return ActionResult(action_id=action.id, success=False, error='Unknown action type')
        except Exception as exc:  # pragma: no cover - runtime safety
            return ActionResult(action_id=action.id, success=False, error=str(exc))

    def _require_gui(self) -> Any:
        if not self._pyautogui:
            raise RuntimeError('pyautogui is not available in this environment')
        return self._pyautogui

    @staticmethod
    def _path_allowed(path: str | Path, approved: bool = False) -> bool:
        resolved = Path(path).expanduser().resolve()
        if policy_service.is_path_allowed(str(resolved)):
            return True
        return approved and settings.allow_outside_paths_with_approval

    @staticmethod
    def _backup_dir(action_id: str) -> Path:
        root = (settings.data_dir / 'rollbacks' / action_id).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _snapshot_path(self, action_id: str, path: Path) -> Path | None:
        source = path.expanduser().resolve()
        if not source.exists():
            return None

        backup_root = self._backup_dir(action_id)
        target = backup_root / source.name
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return target

    def _move_mouse(self, action: ActionEnvelope) -> ActionResult:
        gui = self._require_gui()
        x = int(action.parameters.get('x', 0))
        y = int(action.parameters.get('y', 0))
        duration = float(action.parameters.get('duration', 0.2))
        gui.moveTo(x, y, duration=duration)
        return ActionResult(action_id=action.id, success=True, output={'x': x, 'y': y})

    def _click(self, action: ActionEnvelope) -> ActionResult:
        gui = self._require_gui()
        button = str(action.parameters.get('button', 'left'))
        clicks = int(action.parameters.get('clicks', 1))
        gui.click(button=button, clicks=clicks)
        return ActionResult(action_id=action.id, success=True, output={'button': button, 'clicks': clicks})

    def _type_text(self, action: ActionEnvelope) -> ActionResult:
        gui = self._require_gui()
        text = str(action.parameters.get('text', ''))
        interval = float(action.parameters.get('interval', 0.01))
        gui.write(text, interval=interval)
        return ActionResult(action_id=action.id, success=True, output={'chars': len(text)})

    def _hotkey(self, action: ActionEnvelope) -> ActionResult:
        gui = self._require_gui()
        keys = action.parameters.get('keys', [])
        if not isinstance(keys, list) or not keys:
            raise ValueError('hotkey requires a non-empty keys list')
        gui.hotkey(*keys)
        return ActionResult(action_id=action.id, success=True, output={'keys': keys})

    def _open_app(self, action: ActionEnvelope) -> ActionResult:
        app = str(action.parameters.get('app', '')).strip()
        if not app:
            raise ValueError('open_app requires app parameter')
        app_policy = policy_service.evaluate_app_command(app)
        if app_policy.level == 'blocked':
            raise PermissionError(f'App command blocked by policy: {app_policy.reason} ({app_policy.policy_id})')
        if app_policy.level == 'risky' and not action.requires_approval:
            raise PermissionError(f'App command requires explicit approval due to policy ({app_policy.policy_id})')
        system = platform.system().lower()
        if system == 'windows':
            subprocess.Popen(app, shell=True)
        elif system == 'darwin':
            if app.startswith('open '):
                subprocess.Popen(app, shell=True)
            else:
                subprocess.Popen(['open', '-a', app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            if ' ' in app:
                subprocess.Popen(app, shell=True)
            else:
                subprocess.Popen([app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return ActionResult(action_id=action.id, success=True, output={'app': app})

    def _focus_window(self, action: ActionEnvelope) -> ActionResult:
        title = str(action.parameters.get('title', '')).strip()
        if not title:
            raise ValueError('focus_window requires title')

        try:
            import pygetwindow as gw  # type: ignore

            windows = gw.getWindowsWithTitle(title)
            if windows:
                windows[0].activate()
                return ActionResult(action_id=action.id, success=True, output={'title': title, 'matched': True})
        except Exception:
            pass

        return ActionResult(action_id=action.id, success=False, error=f'No focusable window matched title: {title}')

    def _read_screen(self, action: ActionEnvelope) -> ActionResult:
        gui = self._require_gui()
        screenshot_path = action.parameters.get('path') or str(Path.cwd() / '.jarvisx_data' / 'latest_screen.png')
        path = ensure_directory(screenshot_path)
        image = gui.screenshot()
        image.save(path)
        return ActionResult(action_id=action.id, success=True, output={'path': str(path)})

    def _file_ops(self, action: ActionEnvelope) -> ActionResult:
        op = str(action.parameters.get('op', '')).lower()
        src = action.parameters.get('src')
        dst = action.parameters.get('dst')

        if op == 'read':
            if not src:
                raise ValueError('read operation requires src')
            path = Path(str(src)).expanduser().resolve()
            if not self._path_allowed(path, approved=action.requires_approval):
                raise PermissionError(f'Path is outside allowed roots: {path}')
            content = path.read_text(encoding='utf-8')
            return ActionResult(action_id=action.id, success=True, output={'content': content[:2000], 'truncated': len(content) > 2000})

        if op == 'write':
            if not dst:
                raise ValueError('write operation requires dst')
            path = ensure_directory(str(dst))
            if not self._path_allowed(path, approved=action.requires_approval):
                raise PermissionError(f'Path is outside allowed roots: {path}')
            rollback_backup = self._snapshot_path(action.id, path)
            path.write_text(str(action.parameters.get('content', '')), encoding='utf-8')
            output: dict[str, str | bool] = {'path': str(path), 'written': True}
            if rollback_backup:
                output['rollback_backup'] = str(rollback_backup)
                output['rollback_target'] = str(path)
            else:
                output['rollback_delete_target'] = str(path)
            return ActionResult(action_id=action.id, success=True, output=output)

        if op in {'delete', 'remove'}:
            if not src:
                raise ValueError('delete operation requires src')
            path = Path(str(src)).expanduser().resolve()
            if not self._path_allowed(path, approved=action.requires_approval):
                raise PermissionError(f'Path is outside allowed roots: {path}')
            rollback_backup = self._snapshot_path(action.id, path)
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            output: dict[str, str] = {'deleted': str(path)}
            if rollback_backup:
                output['rollback_backup'] = str(rollback_backup)
                output['rollback_target'] = str(path)
            return ActionResult(action_id=action.id, success=True, output=output)

        if op == 'move':
            if not src or not dst:
                raise ValueError('move operation requires src and dst')
            src_path = Path(str(src)).expanduser().resolve()
            dst_path = Path(str(dst)).expanduser().resolve()
            if not self._path_allowed(src_path, approved=action.requires_approval):
                raise PermissionError(f'Source is outside allowed roots: {src}')
            if not self._path_allowed(dst_path, approved=action.requires_approval):
                raise PermissionError(f'Destination is outside allowed roots: {dst}')
            rollback_backup = self._snapshot_path(action.id, src_path)
            ensure_directory(str(dst_path))
            shutil.move(str(src_path), str(dst_path))
            output: dict[str, str] = {'src': str(src_path), 'dst': str(dst_path)}
            if rollback_backup:
                output['rollback_backup'] = str(rollback_backup)
                output['rollback_target'] = str(src_path)
            return ActionResult(action_id=action.id, success=True, output=output)

        raise ValueError(f'unsupported file op: {op}')

    async def _shell_exec(self, action: ActionEnvelope) -> ActionResult:
        command = str(action.parameters.get('command', '')).strip()
        if not command:
            raise ValueError('shell_exec requires command')
        if len(command) > settings.max_shell_command_length:
            raise PermissionError('Shell command exceeds max_shell_command_length')

        shell_policy = policy_service.evaluate_shell_command(command)
        if shell_policy.level == 'blocked':
            raise PermissionError(f'Shell command blocked by policy: {shell_policy.reason} ({shell_policy.policy_id})')
        if shell_policy.level == 'risky' and not action.requires_approval:
            raise PermissionError(f'Shell command requires explicit approval due to policy ({shell_policy.policy_id})')

        timeout = float(action.parameters.get('timeout_seconds', 60))

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            return ActionResult(action_id=action.id, success=False, error=f'Command timed out after {timeout}s')

        return ActionResult(
            action_id=action.id,
            success=process.returncode == 0,
            output={
                'command': command,
                'returncode': process.returncode,
                'stdout': stdout.decode('utf-8', errors='replace')[:4000],
                'stderr': stderr.decode('utf-8', errors='replace')[:4000],
            },
            error=None if process.returncode == 0 else 'Command failed',
        )

    async def _browser_script(self, action: ActionEnvelope) -> ActionResult:
        url = str(action.parameters.get('url', '')).strip()
        script = str(action.parameters.get('script', '')).strip()
        if not url:
            raise ValueError('browser_script requires url')
        parsed = urlparse(url)
        if parsed.scheme not in {'http', 'https'}:
            raise ValueError('browser_script url must use http/https')

        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            raise RuntimeError(f'playwright is not available: {exc}') from exc

        screenshot_path = str(action.parameters.get('screenshot_path') or Path.cwd() / '.jarvisx_data' / 'browser_script.png')
        screenshot = ensure_directory(screenshot_path)
        headless = bool(action.parameters.get('headless', True))

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=headless)
            page = await browser.new_page()
            await page.goto(url, wait_until='domcontentloaded')
            eval_result = None
            if script:
                eval_result = await page.evaluate(script)
            await page.screenshot(path=str(screenshot), full_page=True)
            title = await page.title()
            await browser.close()

        return ActionResult(
            action_id=action.id,
            success=True,
            output={
                'url': url,
                'title': title,
                'screenshot_path': str(screenshot),
                'eval_result': eval_result,
            },
        )

    async def _http_request(self, action: ActionEnvelope) -> ActionResult:
        method = str(action.parameters.get('method', 'GET')).upper()
        url = str(action.parameters.get('url', '')).strip()
        timeout = float(action.parameters.get('timeout_seconds', 30))
        headers = action.parameters.get('headers', {})
        body = action.parameters.get('body')

        policy = policy_service.evaluate_http_request(method=method, url=url)
        audit_service.log(
            actor='policy',
            action='external_http_policy',
            details=f'context=desktop_engine method={method} url={url} policy={policy.policy_id} level={policy.level}',
        )
        if policy.level == 'blocked':
            raise PermissionError(f'HTTP request blocked: {policy.reason} ({policy.policy_id})')
        if policy.level == 'risky' and not action.requires_approval:
            raise PermissionError(f'HTTP request requires explicit approval due to policy ({policy.policy_id})')

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method=method, url=url, headers=headers, json=body)

        return ActionResult(
            action_id=action.id,
            success=200 <= response.status_code < 400,
            output={
                'method': method,
                'url': url,
                'status_code': response.status_code,
                'headers': dict(response.headers),
                'body_preview': response.text[:2000],
                'policy_id': policy.policy_id,
            },
            error=None if 200 <= response.status_code < 400 else 'HTTP request failed',
        )

    async def _wait(self, action: ActionEnvelope) -> ActionResult:
        seconds = float(action.parameters.get('seconds', 1.0))
        bounded = max(0.0, min(seconds, 300.0))
        await asyncio.sleep(bounded)
        return ActionResult(action_id=action.id, success=True, output={'slept_seconds': bounded})

    def _clipboard_read(self, action: ActionEnvelope) -> ActionResult:
        if not self._pyperclip:
            raise RuntimeError('pyperclip is not available for clipboard_read')
        text = self._pyperclip.paste() or ''
        return ActionResult(action_id=action.id, success=True, output={'text': str(text)[:4000]})

    def _clipboard_write(self, action: ActionEnvelope) -> ActionResult:
        if not self._pyperclip:
            raise RuntimeError('pyperclip is not available for clipboard_write')
        text = str(action.parameters.get('text', ''))
        self._pyperclip.copy(text)
        return ActionResult(action_id=action.id, success=True, output={'chars': len(text)})

    async def apply_rollback(
        self,
        backup_path: str | None,
        target_path: str | None,
        delete_target: str | None = None,
        approved: bool = False,
    ) -> ActionResult:
        if delete_target:
            target = Path(delete_target).expanduser().resolve()
            if not self._path_allowed(target, approved=approved):
                raise PermissionError(f'Rollback target is outside allowed roots: {target}')
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()
            return ActionResult(action_id='rollback', success=True, output={'deleted': str(target)})

        if not backup_path or not target_path:
            raise ValueError('rollback requires backup_path+target_path or delete_target')

        backup = Path(backup_path).expanduser().resolve()
        target = Path(target_path).expanduser().resolve()
        if not backup.exists():
            raise FileNotFoundError(f'Rollback backup does not exist: {backup}')

        if not self._path_allowed(backup, approved=True):
            raise PermissionError(f'Rollback backup is outside allowed roots: {backup}')
        if not self._path_allowed(target, approved=approved):
            raise PermissionError(f'Rollback target is outside allowed roots: {target}')

        if backup.is_dir():
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.copytree(backup, target)
        else:
            ensure_directory(str(target))
            shutil.copy2(backup, target)
        return ActionResult(action_id='rollback', success=True, output={'backup': str(backup), 'restored_to': str(target)})


def build_desktop_engine() -> DesktopEngine:
    if platform.system().lower() == 'windows':
        return WindowsDesktopEngine()
    return SimulatedDesktopEngine()
