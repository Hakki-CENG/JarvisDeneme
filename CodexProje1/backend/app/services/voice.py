from __future__ import annotations

from pathlib import Path

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
    def parse_command(text: str, wake_word: str = 'jarvis') -> dict[str, str | bool]:
        normalized = text.strip()
        lower = normalized.lower()
        ww = wake_word.strip().lower()
        has_wake_word = lower.startswith(ww) or f' {ww} ' in lower
        command = normalized
        if has_wake_word:
            command = lower.replace(ww, '', 1).strip(' ,:;')
        return {
            'has_wake_word': has_wake_word,
            'wake_word': ww,
            'command': command.strip(),
            'raw': normalized,
        }


voice_service = VoiceService()
