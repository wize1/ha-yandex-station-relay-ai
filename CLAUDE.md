# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A Home Assistant custom integration that relays speech between Yandex Alice smart
speakers (Яндекс Станция) and an AI agent of the user's choice, via a
customizable trigger word ("Алиса, попроси **Кузю** …"). Distributed via HACS.

- **Input:** a Yandex Dialogs skill posts the recognised phrase to a webhook
  hosted by this integration. The phrase is relayed to an AI backend; the reply
  is returned as the skill's response so Alice speaks it.
- **Output / slow-answer fallback:** because Yandex Dialogs expect a reply within
  ~3s but LLMs are often slower, slow answers fall back to a short "thinking"
  reply and are then spoken proactively on a configured Yandex Station (via the
  AlexxIT/YandexStation `media_player` TTS), or delivered on the next turn.

## Layout

```
custom_components/yandex_station_relay_ai/
  __init__.py            # config-entry setup, webhook handler, backend dispatch, slow/long-answer queue, services
  manifest.json
  config_flow.py         # UI config flow (user + finish/url) + options flow (backend + behaviour)
  const.py
  services.yaml          # ask, speak
  strings.json
  translations/en.json
  translations/ru.json
hacs.json                # HACS metadata (root)
README.md                # user-facing docs — RUSSIAN (default, rendered by HACS)
README.en.md             # English translation of README.md
```

## Architecture notes

- **Single domain (`yandex_station_relay_ai`), config-entry driven.** All state lives
  in a per-entry `RelayRuntime` under `hass.data[DOMAIN][entry_id]`. No YAML.
- **Webhook ID is the inbound secret.** Generated in `config_flow.async_step_user`
  via `webhook.async_generate_id()`. The webhook is registered with
  `local_only=False` (Yandex calls it from the internet) and `allowed_methods=["POST"]`.
  The finish step shows the full URL via `webhook.async_generate_url`.
- **Two backends, selectable in options** (`CONF_BACKEND`):
  - `conversation` → `conversation.async_converse(...)`, optional `agent_id`.
  - `openai` → POST to `{api_base_url}/chat/completions` (OpenAI-compatible),
    with a short rolling history per `conversation_id` for follow-ups.
- **The ~3s Yandex timeout is the central design constraint.** `_answer` runs the
  backend as a task and `asyncio.wait_for(asyncio.shield(task), first_turn_timeout)`.
  - Fast → reply immediately (`_deliver`, paginating > 1024 chars).
  - Slow → `_queue_slow`: park the task in `self.pending[session_id]`, reply with
    the thinking phrase. If a `tts_entity` is set, a done-callback speaks the full
    answer proactively (`_on_slow_done` → `_speak_then_expire`); otherwise the
    user says "дальше" and `_serve_pending` delivers it next turn.
- **Backend calls go through `_ask_safe`** (never raises → no "task exception
  never retrieved" warnings; errors become the spoken `error_phrase`).
- **Stale-queue guards:** the slow-answer done-callback and the expiry timer both
  identity-check `self.pending.get(session_id) is pending` before acting, so a new
  question that replaces the queue can't be clobbered by an old callback.
- **Yandex response shape** (`_reply`): `{"response": {"text", "tts", "end_session"}, "version": "1.0"}`,
  text/tts truncated to `YANDEX_TEXT_LIMIT` (1024).
- **Services** (`ask`, `speak`) registered once (guarded by `_SERVICES_REGISTERED`)
  and removed when the last entry unloads. `ask` uses `SupportsResponse.OPTIONAL`.

## Working in this repo

- **Code style:** HA core conventions — `from __future__ import annotations`, type
  hints, `_LOGGER = logging.getLogger(__name__)`, async everywhere. Mirror the
  sibling `ha-waha` integration's patterns.
- **Minimum HA version is 2024.12** (`hacs.json`). Options flow uses the modern
  pattern — do **not** assign `self.config_entry` (provided by the base class).
- **Strings + translations stay in sync.** When editing `strings.json`, mirror the
  change into every file under `translations/` (`en.json`, `ru.json`). Keep brand
  names ("Yandex", "Alice", "Home Assistant") untranslated.
- **README is bilingual — keep both in sync.** `README.md` is Russian (the default,
  rendered by HACS); `README.en.md` is the English translation. Edit both together;
  each has a language-switch line at the top.
- **Yandex protocol assumptions** (verified against dialogs docs): request has
  `request.command` / `request.original_utterance`, `session.session_id` /
  `session.skill_id` / `session.new`. Response `text`/`tts` ≤ 1024 chars,
  `end_session` required, reply window ~3s. If Yandex changes the protocol, update
  `_reply` / `handle_webhook`.
- **YandexStation TTS** uses `media_player.play_media` with
  `media_content_type: "text"`. If AlexxIT changes this, update `RelayRuntime.speak`.

## Not yet wired up

- No tests. If adding any, use `pytest-homeassistant-custom-component`.
- No CI/lint config, no `pyproject.toml`.
- No git repo initialized — `git init` before first commit.
- Per-device station mapping (speak the answer on the device the user spoke to)
  is not implemented — proactive answers go to the single configured `tts_entity`.
- A generic non-OpenAI "custom HTTP template" backend is not implemented; the
  `openai` backend covers OpenAI-compatible and most self-hosted servers.
- Repository: `github.com/wize1/ha-yandex-station-relay-ai`. Keep `manifest.json`
  (`documentation`, `issue_tracker`, `codeowners`) and `README.md` aligned if it moves.
```
