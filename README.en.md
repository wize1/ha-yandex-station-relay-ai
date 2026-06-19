[🇷🇺 Русский](README.md) · **🇬🇧 English**

# Yandex Station Relay AI (Кузя)

A Home Assistant custom integration that relays speech between **Yandex Alice
smart speakers (Яндекс Станция)** and an **AI agent of your choice** — via a
customizable trigger word.

> «Алиса, попроси **Кузю** рассказать, что нового в мире» → your AI answers →
> Alice speaks the reply.

The trigger word ("Кузя") is whatever you name the skill. Ask anything after it;
the phrase is relayed to either a Home Assistant **conversation agent** (OpenAI,
Anthropic, Google, Ollama, …) or a **direct OpenAI-compatible / custom
endpoint**, and the answer comes back through Alice.

---

## How it works

```
"Алиса, попроси Кузю <phrase>"
        │
        ▼  Yandex Dialogs  ──HTTPS POST──►  HA webhook (this integration)
                                                  │  strip trigger words
                                                  ▼
                                         AI backend (your choice)
                                                  │
        Alice speaks the answer  ◄──JSON reply────┘
```

Two transports, used together:

1. **Yandex Dialogs skill (primary input).** Your HA instance hosts the skill's
   webhook. Yandex natively understands `«Алиса, попроси <skill> <phrase>»`,
   passes the phrase to the webhook, and speaks back whatever the webhook
   returns.
2. **Yandex Station TTS (output / slow-answer fallback).** Yandex Dialogs expect
   a reply within ~3 seconds, but LLMs are often slower. When the answer is slow,
   the skill replies with a short *"Секунду, думаю…"* and then **speaks the full
   answer proactively through a configured station** (using the
   [AlexxIT/YandexStation](https://github.com/AlexxIT/YandexStation)
   `media_player` TTS). No station configured? It instead asks the user to say
   *"дальше"* to hear the queued answer on the next turn.

Long answers (> 1024 chars, Yandex's limit) are paginated automatically and read
out in parts.

---

## Requirements

- Home Assistant **2024.12+**.
- Your HA reachable over **public HTTPS with a valid certificate** (Nabu Casa
  Cloud, Cloudflare Tunnel, or a reverse proxy). Yandex will not call an
  endpoint without a trusted cert.
- A Yandex account to create the Dialogs skill (free).
- *(Optional, recommended)* the **YandexStation** integration installed and your
  speaker added as a `media_player` — enables proactive spoken answers and the
  `speak` service.

---

## Installation

### HACS (recommended)
1. HACS → ⋮ → **Custom repositories** → add this repo as an **Integration**.
2. Install **Yandex Station Relay AI**, then restart Home Assistant.

### Manual
Copy `custom_components/yandex_station_relay_ai/` into your HA `config/custom_components/`
folder and restart.

---

## Setup

### 1. Add the integration in HA
**Settings → Devices & Services → Add Integration → Yandex Station Relay AI.**

- Give it a name (e.g. `Кузя`).
- *(Optional)* paste your skill's **Skill ID** to reject requests from any other
  skill.
- The final screen shows your **webhook URL** — copy it. It looks like:
  `https://<your-domain>/api/webhook/<random-id>`

### 2. Create the Yandex Dialogs skill
At [dialogs.yandex.ru/developer](https://dialogs.yandex.ru/developer):

1. **Create dialog → Alice skill (Навык в Алисе).**
2. **Name / activation name:** your trigger word, e.g. `Кузя`. This is what makes
   `«Алиса, попроси Кузю …»` work.
3. **Backend:** choose **Webhook** and paste the URL from step 1.
4. Set the skill **language to Russian**.
5. Save. You can use the skill on your own linked devices in **draft/test** mode —
   no public moderation needed for personal use. (Publishing makes `попроси Кузю`
   work everywhere; testing mode works on your account's devices.)

### 3. Pick your AI backend
On the integration card → **Configure**:

- **Home Assistant conversation agent** — route to any Assist agent you've set up
  (OpenAI, Anthropic, Google Generative AI, Ollama, custom). Leave *Conversation
  agent ID* blank for the default agent. This is the "agent of common choice".
- **OpenAI-compatible / custom endpoint** — call any `/chat/completions` API
  directly: OpenAI, OpenRouter, LM Studio, vLLM, Ollama's OpenAI endpoint, or
  your own server. Set base URL, API key (if any), model, and system prompt.

Also configure here: the **Yandex Station** for proactive answers, trigger words
to strip, the greeting / thinking / error phrases, and timeouts.

### 4. Try it
> «Алиса, попроси Кузю придумать рифму к слову дом»

---

## Services

### `yandex_station_relay_ai.ask`
Relay text to the configured AI and return its reply (optionally speak it).
Useful in automations or as the "YandexStation path".

```yaml
action: yandex_station_relay_ai.ask
data:
  text: "Какая погода обычно в июне в Лондоне?"
  speak: true                                   # speak on a station
  target: media_player.yandex_station_kitchen   # optional; defaults to configured station
response_variable: result
# result.text -> the AI answer
```

### `yandex_station_relay_ai.speak`
Speak arbitrary text on a station — no AI call, just TTS.

```yaml
action: yandex_station_relay_ai.speak
data:
  text: "Ужин готов"
  target: media_player.yandex_station_kitchen
```

---

## Behaviour notes & tuning

- **First-reply timeout** (default 2.5 s): how long to wait for the AI before the
  *"думаю…"* fallback. Keep it under ~3 s — Yandex drops slower responses.
- **Keep replies short and speakable.** The default system prompt asks for one or
  two sentences, no markdown. Tune it for your backend.
- **Trigger words** like `кузя`/`кузю` are stripped from the start of the phrase;
  connectors like `попроси`, `спроси`, `алиса` are always stripped.
- **Per-session context:** each Alice dialog gets its own conversation thread, so
  follow-up questions keep context.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Alice: "навык не отвечает" | AI slower than the timeout and no station set — configure a station for proactive answers, or lower `max_tokens`. |
| Yandex can't save the webhook | HA not reachable over public HTTPS with a valid cert. |
| Nothing happens | Webhook URL mismatch, or `skill_id` filter set but not matching. Check HA logs (`yandex_station_relay_ai`). |
| Proactive answer never spoken | `tts_entity` not set, or it isn't a working YandexStation `media_player`. |

---

## Limitations

- Free-form phrase capture **requires the Dialogs skill** (a public HTTPS
  webhook). YandexStation alone cannot hand HA arbitrary spoken text — it is used
  here for **output** (TTS) and the `ask`/`speak` services.
- Proactive answers are spoken on the single configured station, not
  automatically on whichever device the user spoke to.
