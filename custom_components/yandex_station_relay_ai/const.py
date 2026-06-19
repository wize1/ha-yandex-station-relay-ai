"""Constants for the Yandex Station Relay AI integration."""

from __future__ import annotations

DOMAIN = "yandex_station_relay_ai"

# --- Config entry data (set once, in the config flow) ---
CONF_WEBHOOK_ID = "webhook_id"
CONF_SKILL_ID = "skill_id"

# --- Options (editable via the options flow) ---
CONF_BACKEND = "backend"
BACKEND_CONVERSATION = "conversation"
BACKEND_OPENAI = "openai"

# conversation-agent backend
CONF_CONVERSATION_AGENT = "conversation_agent"
CONF_LANGUAGE = "language"

# openai-compatible backend
CONF_API_BASE_URL = "api_base_url"
CONF_API_KEY = "api_key"
CONF_MODEL = "model"
CONF_SYSTEM_PROMPT = "system_prompt"
CONF_MAX_TOKENS = "max_tokens"

# relay behaviour
CONF_TRIGGER_PHRASES = "trigger_phrases"
CONF_TTS_ENTITY = "tts_entity"
CONF_FIRST_TURN_TIMEOUT = "first_turn_timeout"
CONF_BACKEND_TIMEOUT = "backend_timeout"
CONF_GREETING = "greeting"
CONF_THINKING_PHRASE = "thinking_phrase"
CONF_ERROR_PHRASE = "error_phrase"
CONF_END_SESSION = "end_session"

# --- Defaults ---
DEFAULT_LANGUAGE = "ru-RU"
DEFAULT_SYSTEM_PROMPT = (
    "Ты — голосовой помощник по имени Кузя, встроенный в умный дом. "
    "Отвечай кратко и по делу, на русском языке, одним-двумя предложениями. "
    "Не используй markdown, списки, ссылки или эмодзи — ответ будет произнесён вслух."
)
DEFAULT_API_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_MAX_TOKENS = 512
DEFAULT_FIRST_TURN_TIMEOUT = 2.5
DEFAULT_BACKEND_TIMEOUT = 60
DEFAULT_GREETING = "Привет! Я Кузя. О чём спросить?"
DEFAULT_THINKING_PHRASE = "Секунду, думаю над ответом…"
DEFAULT_ERROR_PHRASE = "Извините, не получилось получить ответ. Попробуйте ещё раз."
DEFAULT_END_SESSION = False
DEFAULT_TRIGGER_PHRASES = "кузя, кузю, кузе"

# Built-in connector words always stripped from the start of the recognised
# phrase, in addition to the user's configured trigger words.
CONNECTOR_WORDS = frozenset({"алиса", "попроси", "спроси", "у", "скажи", "передай"})

# Hard protocol limits / wire constants.
YANDEX_TEXT_LIMIT = 1024
PROTOCOL_VERSION = "1.0"

# Per-entry conversation history cap (messages) for the openai backend.
HISTORY_LIMIT = 12

# Followups the user can say to fetch a queued (slow) answer.
FOLLOWUP_HINT = "Скажите «дальше», когда будете готовы."
