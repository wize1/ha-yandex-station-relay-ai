"""The Yandex Station Relay AI integration.

Bridges a Yandex Dialogs skill ("Алиса, попроси Кузю …") to an AI backend of
the user's choice and speaks the answer back through Alice. The user's HA
instance hosts the skill webhook; the recognised phrase is relayed to either a
Home Assistant conversation agent or a direct OpenAI-compatible endpoint, and
the reply is returned to Yandex so Alice speaks it.

Because Yandex Dialogs expects a reply within a few seconds but LLMs are often
slower, slow answers fall back to a short "thinking" reply and are then either
delivered on the next turn ("дальше") or spoken proactively on a configured
Yandex Station (via the YandexStation media_player TTS).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from aiohttp import web

from homeassistant.components import conversation, webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import (
    Context,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .const import (
    BACKEND_CONVERSATION,
    BACKEND_OPENAI,
    CONF_API_BASE_URL,
    CONF_API_KEY,
    CONF_BACKEND,
    CONF_BACKEND_TIMEOUT,
    CONF_CONVERSATION_AGENT,
    CONF_END_SESSION,
    CONF_ERROR_PHRASE,
    CONF_FIRST_TURN_TIMEOUT,
    CONF_GREETING,
    CONF_LANGUAGE,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    CONF_SKILL_ID,
    CONF_SYSTEM_PROMPT,
    CONF_THINKING_PHRASE,
    CONF_TRIGGER_PHRASES,
    CONF_TTS_ENTITY,
    CONF_WEBHOOK_ID,
    CONNECTOR_WORDS,
    DEFAULT_API_BASE_URL,
    DEFAULT_BACKEND_TIMEOUT,
    DEFAULT_END_SESSION,
    DEFAULT_ERROR_PHRASE,
    DEFAULT_FIRST_TURN_TIMEOUT,
    DEFAULT_GREETING,
    DEFAULT_LANGUAGE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_THINKING_PHRASE,
    DEFAULT_TRIGGER_PHRASES,
    DOMAIN,
    FOLLOWUP_HINT,
    HISTORY_LIMIT,
    PROTOCOL_VERSION,
    YANDEX_TEXT_LIMIT,
)

_LOGGER = logging.getLogger(__name__)

# Words that, when said alone, mean "give me the queued answer" rather than a
# new question.
_FOLLOWUP_WORDS = frozenset(
    {"дальше", "ещё", "еще", "продолжи", "продолжай", "да", "и", "ну", "готов", "готова"}
)

_SERVICES_REGISTERED = f"{DOMAIN}_services_registered"


@dataclass
class _Pending:
    """A queued answer for an Alice session.

    Either ``task`` (a slow backend call still in flight / just finished) or
    ``chunks`` (the remaining pieces of a long answer) is set.
    """

    task: asyncio.Task[str] | None = None
    chunks: list[str] = field(default_factory=list)
    spoken: bool = False


class RelayRuntime:
    """Per-config-entry state and behaviour."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.pending: dict[str, _Pending] = {}
        self._history: dict[str, list[dict[str, str]]] = {}

    # -- convenience accessors over current options ------------------------

    @property
    def _opt(self) -> dict[str, Any]:
        return self.entry.options

    @property
    def skill_id(self) -> str | None:
        return self.entry.data.get(CONF_SKILL_ID) or None

    @property
    def backend(self) -> str:
        return self._opt.get(CONF_BACKEND, BACKEND_CONVERSATION)

    @property
    def language(self) -> str:
        return self._opt.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)

    @property
    def tts_entity(self) -> str | None:
        return self._opt.get(CONF_TTS_ENTITY) or None

    @property
    def first_turn_timeout(self) -> float:
        return float(self._opt.get(CONF_FIRST_TURN_TIMEOUT, DEFAULT_FIRST_TURN_TIMEOUT))

    @property
    def backend_timeout(self) -> float:
        return float(self._opt.get(CONF_BACKEND_TIMEOUT, DEFAULT_BACKEND_TIMEOUT))

    @property
    def greeting(self) -> str:
        return self._opt.get(CONF_GREETING, DEFAULT_GREETING)

    @property
    def thinking_phrase(self) -> str:
        return self._opt.get(CONF_THINKING_PHRASE, DEFAULT_THINKING_PHRASE)

    @property
    def error_phrase(self) -> str:
        return self._opt.get(CONF_ERROR_PHRASE, DEFAULT_ERROR_PHRASE)

    @property
    def end_session(self) -> bool:
        return bool(self._opt.get(CONF_END_SESSION, DEFAULT_END_SESSION))

    @property
    def _trigger_words(self) -> frozenset[str]:
        raw = self._opt.get(CONF_TRIGGER_PHRASES, DEFAULT_TRIGGER_PHRASES) or ""
        words = {w.strip().lower() for w in raw.replace(",", " ").split() if w.strip()}
        return frozenset(words | CONNECTOR_WORDS)

    # -- backend dispatch --------------------------------------------------

    async def ask(self, text: str, conversation_id: str) -> str:
        """Send ``text`` to the configured backend and return the reply text."""
        if self.backend == BACKEND_OPENAI:
            return await self._ask_openai(text, conversation_id)
        return await self._ask_conversation(text, conversation_id)

    async def _ask_conversation(self, text: str, conversation_id: str) -> str:
        agent_id = self._opt.get(CONF_CONVERSATION_AGENT) or None
        result = await conversation.async_converse(
            self.hass,
            text=text,
            conversation_id=conversation_id,
            context=Context(),
            language=self.language,
            agent_id=agent_id,
        )
        speech = result.response.speech.get("plain", {}).get("speech", "")
        return speech.strip() or "Готово."

    async def _ask_openai(self, text: str, conversation_id: str) -> str:
        base_url = (self._opt.get(CONF_API_BASE_URL) or DEFAULT_API_BASE_URL).rstrip("/")
        api_key = self._opt.get(CONF_API_KEY) or ""
        model = self._opt.get(CONF_MODEL) or DEFAULT_MODEL
        system_prompt = self._opt.get(CONF_SYSTEM_PROMPT) or DEFAULT_SYSTEM_PROMPT
        max_tokens = int(self._opt.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS))

        history = self._history.setdefault(conversation_id, [])
        messages = (
            [{"role": "system", "content": system_prompt}]
            + history
            + [{"role": "user", "content": text}]
        )
        body = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.6,
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        session = async_get_clientsession(self.hass)
        async with session.post(
            f"{base_url}/chat/completions",
            json=body,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=self.backend_timeout),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

        answer = (data["choices"][0]["message"]["content"] or "").strip()
        # Persist short rolling context for natural follow-ups.
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": answer})
        if len(history) > HISTORY_LIMIT:
            del history[: len(history) - HISTORY_LIMIT]
        return answer or "Готово."

    async def _ask_safe(self, text: str, conversation_id: str) -> str:
        """Backend call that never raises — returns the error phrase instead."""
        try:
            return await self.ask(text, conversation_id)
        except Exception:  # noqa: BLE001 - surfaced to the user as speech
            _LOGGER.exception("Backend call failed for %s", conversation_id)
            return self.error_phrase

    # -- speaking through a Yandex Station ---------------------------------

    async def speak(self, text: str, entity_id: str | None = None) -> None:
        """Speak ``text`` on a Yandex Station via media_player TTS."""
        target = entity_id or self.tts_entity
        if not target:
            raise HomeAssistantError(
                "No target station given and no default TTS station configured."
            )
        for chunk in _chunk(text, YANDEX_TEXT_LIMIT):
            await self.hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": target,
                    "media_content_id": chunk,
                    "media_content_type": "text",
                },
                blocking=True,
            )

    # -- webhook handling --------------------------------------------------

    async def handle_webhook(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except ValueError:
            return _json(self._reply("Не удалось разобрать запрос.", end=True))

        session = payload.get("session") or {}
        req = payload.get("request") or {}

        if self.skill_id and session.get("skill_id") != self.skill_id:
            _LOGGER.warning(
                "Rejected webhook: skill_id %s does not match configured %s",
                session.get("skill_id"),
                self.skill_id,
            )
            return _json(self._reply("Доступ запрещён.", end=True))

        session_id = session.get("session_id", "")
        conversation_id = f"alice:{session_id}"
        command = (req.get("command") or "").strip()

        # A queued answer from a previous (slow / long) turn takes priority.
        if (pending := self.pending.get(session_id)) is not None:
            if _is_followup(command):
                return await self._serve_pending(session_id, pending)
            # User asked something new instead of waiting — drop the stale queue.
            self._discard_pending(session_id)

        question = self._strip_triggers(command)
        if not question:
            return _json(self._reply(self.greeting, end=False))

        return await self._answer(session_id, conversation_id, question)

    async def _answer(
        self, session_id: str, conversation_id: str, question: str
    ) -> web.Response:
        """Run the backend with the first-turn timeout, queueing if slow."""
        task = self.hass.async_create_task(
            self._ask_safe(question, conversation_id), eager_start=False
        )
        try:
            answer = await asyncio.wait_for(
                asyncio.shield(task), timeout=self.first_turn_timeout
            )
        except asyncio.TimeoutError:
            return self._queue_slow(session_id, task)
        return self._deliver(session_id, answer)

    def _queue_slow(self, session_id: str, task: asyncio.Task[str]) -> web.Response:
        """Backend is slow: park the task and tell the user we're thinking."""
        pending = _Pending(task=task)
        self.pending[session_id] = pending
        if self.tts_entity:
            # Speak the answer proactively the moment it is ready.
            task.add_done_callback(
                lambda t, sid=session_id, p=pending: self._on_slow_done(sid, p, t)
            )
            hint = ""
        else:
            hint = " " + FOLLOWUP_HINT
        return _json(self._reply(self.thinking_phrase + hint, end=False))

    def _on_slow_done(
        self, session_id: str, pending: _Pending, task: asyncio.Task[str]
    ) -> None:
        """Done-callback: push a slow answer to the station, then expire it."""
        # Only act if this is still the live queue for the session (the user may
        # have asked something new, replacing or clearing it).
        if self.pending.get(session_id) is not pending or pending.spoken:
            return
        answer = _result_or(task, self.error_phrase)
        # Claim it optimistically so a racing "дальше" can't double-answer.
        pending.spoken = True
        self.hass.async_create_task(self._speak_then_expire(session_id, pending, answer))

    async def _speak_then_expire(
        self, session_id: str, pending: _Pending, answer: str
    ) -> None:
        try:
            await self.speak(answer)
        except Exception:  # noqa: BLE001
            # Couldn't speak it — reopen so the "дальше" follow-up still delivers.
            _LOGGER.exception("Failed to speak slow answer on station")
            pending.spoken = False
            return
        # Keep the queue briefly so a "дальше" follow-up is answered gracefully,
        # then drop it (only if it is still the same queued item).
        self.hass.loop.call_later(120, self._expire, session_id, pending)

    def _expire(self, session_id: str, pending: _Pending) -> None:
        if self.pending.get(session_id) is pending:
            self.pending.pop(session_id, None)

    async def _serve_pending(self, session_id: str, pending: _Pending) -> web.Response:
        # Case 1: remaining chunks of a long answer.
        if pending.task is None:
            chunk = pending.chunks.pop(0)
            if pending.chunks:
                return _json(self._reply(chunk + " …", end=False))
            self.pending.pop(session_id, None)
            return _json(self._reply(chunk, end=self.end_session))

        # Case 2: a slow backend task.
        if pending.spoken:
            self.pending.pop(session_id, None)
            return _json(self._reply("Я ответил вслух на колонке.", end=self.end_session))

        if not pending.task.done():
            try:
                answer = await asyncio.wait_for(
                    asyncio.shield(pending.task), timeout=self.first_turn_timeout
                )
            except asyncio.TimeoutError:
                return _json(self._reply("Ещё думаю, секунду…", end=False))
        else:
            answer = _result_or(pending.task, self.error_phrase)

        self.pending.pop(session_id, None)
        return self._deliver(session_id, answer)

    def _deliver(self, session_id: str, answer: str) -> web.Response:
        """Turn a full answer into a response, paginating if over the limit."""
        chunks = _chunk(answer, YANDEX_TEXT_LIMIT)
        if len(chunks) == 1:
            return _json(self._reply(chunks[0], end=self.end_session))
        self.pending[session_id] = _Pending(chunks=chunks[1:])
        return _json(self._reply(chunks[0] + " …", end=False))

    # -- helpers -----------------------------------------------------------

    def _discard_pending(self, session_id: str) -> None:
        pending = self.pending.pop(session_id, None)
        if pending and pending.task is not None and not pending.task.done():
            pending.task.cancel()

    def _strip_triggers(self, text: str) -> str:
        """Drop leading trigger/connector words (Кузя, попроси, …)."""
        if not text:
            return ""
        words = text.split()
        triggers = self._trigger_words
        i = 0
        while i < len(words) and words[i].lower().strip(",.!?") in triggers:
            i += 1
        return " ".join(words[i:]).strip()

    def _reply(self, text: str, *, end: bool) -> dict[str, Any]:
        text = text[:YANDEX_TEXT_LIMIT]
        return {
            "response": {"text": text, "tts": text, "end_session": end},
            "version": PROTOCOL_VERSION,
        }

    def shutdown(self) -> None:
        for session_id in list(self.pending):
            self._discard_pending(session_id)
        self._history.clear()


# --- module-level helpers ----------------------------------------------------


def _json(body: dict[str, Any]) -> web.Response:
    return web.json_response(body)


def _is_followup(command: str) -> bool:
    if not command:
        return True
    tokens = [t.strip(",.!?").lower() for t in command.split()]
    return all(t in _FOLLOWUP_WORDS for t in tokens)


def _result_or(task: asyncio.Task[str], fallback: str) -> str:
    try:
        return task.result()
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Queued backend task failed")
        return fallback


def _chunk(text: str, limit: int) -> list[str]:
    """Split ``text`` into <=limit pieces, preferring sentence/space breaks."""
    text = text.strip()
    if len(text) <= limit:
        return [text or "…"]
    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        else:
            cut += 1
        chunks.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        chunks.append(rest)
    return chunks


# --- setup / teardown --------------------------------------------------------


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Yandex Station Relay AI config entry."""
    runtime = RelayRuntime(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime

    webhook_id = entry.data[CONF_WEBHOOK_ID]
    webhook.async_register(
        hass,
        DOMAIN,
        entry.data.get(CONF_NAME, "Yandex Station Relay AI"),
        webhook_id,
        _make_handler(runtime),
        local_only=False,
        allowed_methods=["POST"],
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])
    runtime: RelayRuntime = hass.data[DOMAIN].pop(entry.entry_id)
    runtime.shutdown()
    if not hass.data[DOMAIN]:
        for service in ("ask", "speak"):
            hass.services.async_remove(DOMAIN, service)
        hass.data.pop(DOMAIN, None)
        hass.data.pop(_SERVICES_REGISTERED, None)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _make_handler(runtime: RelayRuntime):
    async def _handler(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        return await runtime.handle_webhook(request)

    return _handler


# --- services ----------------------------------------------------------------


def _pick_runtime(hass: HomeAssistant, entry_id: str | None) -> RelayRuntime:
    entries: dict[str, RelayRuntime] = hass.data.get(DOMAIN, {})
    if not entries:
        raise HomeAssistantError("Yandex Station Relay AI is not configured.")
    if entry_id:
        if entry_id not in entries:
            raise HomeAssistantError(f"Unknown Yandex Station Relay AI entry: {entry_id}")
        return entries[entry_id]
    return next(iter(entries.values()))


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.data.get(_SERVICES_REGISTERED):
        return

    ask_schema = vol.Schema(
        {
            vol.Required("text"): cv.string,
            vol.Optional("speak", default=False): cv.boolean,
            vol.Optional("target"): cv.entity_id,
            vol.Optional("entry_id"): cv.string,
        }
    )
    speak_schema = vol.Schema(
        {
            vol.Required("text"): cv.string,
            vol.Optional("target"): cv.entity_id,
            vol.Optional("entry_id"): cv.string,
        }
    )

    async def _ask(call: ServiceCall) -> ServiceResponse:
        runtime = _pick_runtime(hass, call.data.get("entry_id"))
        text: str = call.data["text"]
        answer = await runtime.ask(text, conversation_id=f"service:{call.context.id}")
        target = call.data.get("target") or runtime.tts_entity
        if call.data["speak"] and target:
            await runtime.speak(answer, target)
        return {"text": answer}

    async def _speak(call: ServiceCall) -> None:
        runtime = _pick_runtime(hass, call.data.get("entry_id"))
        await runtime.speak(call.data["text"], call.data.get("target"))

    hass.services.async_register(
        DOMAIN, "ask", _ask, schema=ask_schema, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(DOMAIN, "speak", _speak, schema=speak_schema)
    hass.data[_SERVICES_REGISTERED] = True
