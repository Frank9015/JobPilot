"""
JobPilot — Telegram Notifier
Implementación de InterventionNotifier para Telegram Bot.
Envía alertas por Telegram y puede recibir respuestas via polling de updates.

Requiere:
  - TELEGRAM_BOT_TOKEN en .env
  - TELEGRAM_CHAT_ID en .env
  - Haber iniciado el bot con /start en Telegram

Si las credenciales no están configuradas, el notifier se degrada
silenciosamente (notify retorna False, wait retorna None).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from jobpilot.core.config import get_settings
from jobpilot.core.logger import get_logger

logger = get_logger("intervention.telegram")

# Offset global para no re-leer updates ya procesados
_last_update_id: int = 0


class TelegramNotifier:
    """
    Notificador por Telegram Bot API (HTTP puro, sin dependencias externas).
    Usa urllib para evitar dependencia de requests/httpx.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._token = settings.telegram_bot_token
        self._chat_id = settings.telegram_chat_id
        self._configured = bool(self._token and self._chat_id)

        if not self._configured:
            logger.debug(
                "Telegram no configurado (TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID vacíos). "
                "El notifier se desactivará silenciosamente."
            )

    @property
    def channel_name(self) -> str:
        return "telegram"

    # ── Notificación ──────────────────────────────────────────────────────────
    def notify(self, intervention) -> bool:
        """Envía un mensaje de alerta por Telegram."""
        if not self._configured:
            return False

        reason_emoji = {
            "captcha": "🔒",
            "mfa": "🔐",
            "unknown_question": "❓",
            "error": "⚠️",
        }

        emoji = reason_emoji.get(intervention.reason, "🚨")

        lines = [
            f"{emoji} *INTERVENCIÓN REQUERIDA*",
            "",
            f"*Motivo:* {intervention.reason}",
            f"*Oferta:* {_escape_md(intervention.job_title)}",
            f"*Empresa:* {_escape_md(intervention.company)}",
            f"*Portal:* {intervention.portal.upper()}",
        ]

        if intervention.question:
            lines.append("")
            lines.append(f"*Pregunta:* {_escape_md(intervention.question)}")

        lines.append("")
        lines.append(
            "_Responde a este mensaje con tu respuesta, "
            "'skip' para saltar, o 'done' si ya resolviste en el browser._"
        )

        message = "\n".join(lines)
        return self._send_message(message, parse_mode="Markdown")

    # ── Espera de respuesta ───────────────────────────────────────────────────
    def wait_for_response(
        self,
        intervention_id: uuid.UUID,
        timeout_seconds: int,
        poll_interval: int,
    ) -> str | None:
        """Espera una respuesta del usuario por Telegram usando long polling."""
        if not self._configured:
            return None

        global _last_update_id

        deadline = time.time() + timeout_seconds
        logger.info(f"Esperando respuesta por Telegram (timeout: {timeout_seconds}s)...")

        while time.time() < deadline:
            try:
                updates = self._get_updates(offset=_last_update_id + 1, timeout=min(poll_interval, 30))

                for update in updates:
                    update_id = update.get("update_id", 0)
                    _last_update_id = max(_last_update_id, update_id)

                    message = update.get("message", {})
                    chat_id = str(message.get("chat", {}).get("id", ""))
                    text = message.get("text", "").strip()

                    # Solo procesar mensajes del chat configurado
                    if chat_id != self._chat_id:
                        continue

                    if not text:
                        continue

                    # Respuesta recibida
                    if text.lower() == "skip":
                        logger.info("Usuario respondió 'skip' por Telegram")
                        self._send_message("⏭️ Oferta saltada.")
                        return None

                    logger.info(f"Respuesta recibida por Telegram: '{text[:50]}'")
                    self._send_message(f"✅ Respuesta registrada: _{_escape_md(text[:80])}_", parse_mode="Markdown")
                    return text

            except Exception as e:
                logger.debug(f"Error en polling Telegram: {e}")
                time.sleep(poll_interval)

        # Timeout
        self._send_message("⏳ Timeout — saltando a la siguiente oferta.")
        return None

    # ── HTTP helpers (urllib, sin dependencias extra) ──────────────────────────
    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self._token}/{method}"

    def _send_message(self, text: str, parse_mode: str = "") -> bool:
        """Envía un mensaje al chat configurado."""
        payload: dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self._api_url("sendMessage"),
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                return result.get("ok", False)
        except Exception as e:
            logger.error(f"Error enviando mensaje Telegram: {e}")
            return False

    def _get_updates(self, offset: int = 0, timeout: int = 5) -> list[dict]:
        """Obtiene updates pendientes del bot."""
        params = f"?offset={offset}&timeout={timeout}&allowed_updates=[\"message\"]"
        try:
            req = urllib.request.Request(self._api_url("getUpdates") + params)
            with urllib.request.urlopen(req, timeout=timeout + 5) as resp:
                result = json.loads(resp.read())
                if result.get("ok"):
                    return result.get("result", [])
        except urllib.error.URLError:
            pass  # Network timeout is normal during long polling
        except Exception as e:
            logger.debug(f"Error obteniendo updates Telegram: {e}")
        return []


# ── Utilidades ────────────────────────────────────────────────────────────────
def _escape_md(text: str) -> str:
    """Escapa caracteres especiales para Markdown de Telegram."""
    for char in ("_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"):
        text = text.replace(char, f"\\{char}")
    return text
