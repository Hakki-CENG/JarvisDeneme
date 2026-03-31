from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from app.services.policy_service import policy_service


class VoiceService:
    def __init__(self) -> None:
        self._speech_recognition = None
        self._pyttsx3 = None

        try:
            import speech_recognition as sr

            self._speech_recognition = sr
        except Exception:
            self._speech_recognition = None

        try:
            import pyttsx3

            self._pyttsx3 = pyttsx3.init()
        except Exception:
            self._pyttsx3 = None

    def transcribe_file(self, path: str) -> str:
        if not self._speech_recognition:
            return 'Voice transcription package is unavailable in current environment.'

        audio_path = Path(path).expanduser().resolve()
        if not policy_service.is_path_allowed(str(audio_path)):
            return f'Audio path is outside allowed roots: {audio_path}'
        if not audio_path.exists():
            return f'Audio file does not exist: {audio_path}'
        recognizer = self._speech_recognition.Recognizer()
        with self._speech_recognition.AudioFile(str(audio_path)) as source:
            data = recognizer.record(source)
        try:
            return recognizer.recognize_google(data)
        except Exception as exc:
            return f'Voice transcription failed: {exc}'

    def transcribe_microphone(self, timeout_seconds: float = 8.0, phrase_time_limit: float = 12.0) -> str:
        if not self._speech_recognition:
            return 'Voice transcription package is unavailable in current environment.'

        recognizer = self._speech_recognition.Recognizer()
        try:
            with self._speech_recognition.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio = recognizer.listen(source, timeout=timeout_seconds, phrase_time_limit=phrase_time_limit)
            return recognizer.recognize_google(audio)
        except Exception as exc:
            return f'Microphone transcription failed: {exc}'

    def speak(self, text: str) -> str:
        if not self._pyttsx3:
            return 'Text-to-speech package is unavailable in current environment.'

        self._pyttsx3.say(text)
        self._pyttsx3.runAndWait()
        return 'ok'

    @staticmethod
    def parse_command(text: str, wake_word: str = 'jarvis') -> dict[str, Any]:
        normalized = ' '.join(text.strip().split())
        ww = wake_word.strip().lower()
        wake_pattern = rf'\b{re.escape(ww)}\b'
        has_wake_word = bool(re.search(wake_pattern, normalized, flags=re.IGNORECASE))

        command = normalized
        if has_wake_word:
            command = re.sub(wake_pattern, '', normalized, count=1, flags=re.IGNORECASE).strip(' ,:;.-')
        command_lower = command.lower()

        intent = 'task_request'
        if not command:
            intent = 'empty'
        elif any(marker in command_lower for marker in ['acil durdur', 'emergency stop', 'tümünü durdur', 'stop everything']):
            intent = 'safety_stop'
        elif any(marker in command_lower for marker in ['acil modu kapat', 'emergency clear', 'stopu kaldır']):
            intent = 'safety_clear'
        elif any(marker in command_lower for marker in ['durum', 'status', 'rapor', 'health']):
            intent = 'status_query'

        action_hint = 'general'
        if re.search(r'https?://\S+', command_lower):
            action_hint = 'web_navigation'
        elif any(token in command_lower for token in ['chrome', 'edge', 'firefox', 'tarayıcı']):
            action_hint = 'app_launch'
        elif any(token in command_lower for token in ['terminal', 'powershell', 'shell', 'komut çalıştır']):
            action_hint = 'shell_exec'
        elif any(token in command_lower for token in ['dosyaya yaz', 'save file', 'kaydet']):
            action_hint = 'file_write'

        url_match = re.search(r'https?://\S+', command, flags=re.IGNORECASE)
        app_candidates = ['chrome', 'msedge', 'edge', 'firefox', 'notepad', 'explorer']
        app_name = next((name for name in app_candidates if name in command_lower), '')

        entities = {
            'url': (url_match.group(0).rstrip('.,)') if url_match else ''),
            'app': app_name,
        }
        if action_hint == 'shell_exec':
            entities['shell_command'] = command

        return {
            'has_wake_word': has_wake_word,
            'wake_word': ww,
            'command': command.strip(),
            'raw': normalized,
            'intent': intent,
            'action_hint': action_hint,
            'entities': entities,
            'suggested_objective': command.strip() if has_wake_word and command.strip() else '',
        }


voice_service = VoiceService()
