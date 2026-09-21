"""Voice provider — text-to-speech and speech-to-text via OpenAI API."""
import os
import httpx
import base64


class VoiceProvider:
    """OpenAI voice: TTS (text-to-speech) and STT (speech-to-text)."""

    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = "https://api.openai.com/v1"

    async def text_to_speech(self, text: str, voice: str = "alloy") -> bytes:
        """Convert text to speech audio bytes (MP3)."""
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "tts-1",
            "input": text,
            "voice": voice,
            "response_format": "mp3",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.base_url}/audio/speech",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                return resp.content
        except httpx.HTTPStatusError as e:
            raise ValueError(f"TTS API error: {e.response.status_code}")

    async def speech_to_text(self, audio_bytes: bytes, filename: str = "audio.webm") -> str:
        """Convert speech audio bytes to text."""
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        files = {
            "file": (filename, audio_bytes, "audio/webm"),
        }

        data = {
            "model": "whisper-1",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.base_url}/audio/transcriptions",
                    headers=headers,
                    data=data,
                    files=files,
                )
                resp.raise_for_status()
                result = resp.json()
                return result.get("text", "")
        except httpx.HTTPStatusError as e:
            raise ValueError(f"STT API error: {e.response.status_code}")
