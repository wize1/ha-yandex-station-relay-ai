"""Config and options flow for Yandex Station Relay AI."""

from __future__ import annotations

from typing import Any

from homeassistant.components import webhook
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.network import NoURLAvailableError
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
)


def _default_options() -> dict[str, Any]:
    """Options that make the integration usable before it is configured."""
    return {
        CONF_BACKEND: BACKEND_CONVERSATION,
        CONF_LANGUAGE: DEFAULT_LANGUAGE,
        CONF_API_BASE_URL: DEFAULT_API_BASE_URL,
        CONF_MODEL: DEFAULT_MODEL,
        CONF_SYSTEM_PROMPT: DEFAULT_SYSTEM_PROMPT,
        CONF_MAX_TOKENS: DEFAULT_MAX_TOKENS,
        CONF_TRIGGER_PHRASES: DEFAULT_TRIGGER_PHRASES,
        CONF_FIRST_TURN_TIMEOUT: DEFAULT_FIRST_TURN_TIMEOUT,
        CONF_BACKEND_TIMEOUT: DEFAULT_BACKEND_TIMEOUT,
        CONF_GREETING: DEFAULT_GREETING,
        CONF_THINKING_PHRASE: DEFAULT_THINKING_PHRASE,
        CONF_ERROR_PHRASE: DEFAULT_ERROR_PHRASE,
        CONF_END_SESSION: DEFAULT_END_SESSION,
    }


class YandexStationRelayAiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data = {
                CONF_NAME: user_input[CONF_NAME],
                CONF_SKILL_ID: user_input.get(CONF_SKILL_ID, "").strip(),
                CONF_WEBHOOK_ID: webhook.async_generate_id(),
            }
            return await self.async_step_finish()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Кузя"): str,
                vol.Optional(CONF_SKILL_ID, default=""): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        webhook_id = self._data[CONF_WEBHOOK_ID]
        try:
            url = webhook.async_generate_url(self.hass, webhook_id)
        except NoURLAvailableError:
            url = f"https://<your-external-url>/api/webhook/{webhook_id}"

        if user_input is not None:
            return self.async_create_entry(
                title=self._data[CONF_NAME],
                data=self._data,
                options=_default_options(),
            )

        return self.async_show_form(
            step_id="finish",
            data_schema=vol.Schema({}),
            description_placeholders={"url": url},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return YandexStationRelayAiOptionsFlow()


class YandexStationRelayAiOptionsFlow(OptionsFlow):
    """Edit relay behaviour and the AI backend."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = {**_default_options(), **self.config_entry.options}

        schema = vol.Schema(
            {
                vol.Required(CONF_BACKEND, default=opts[CONF_BACKEND]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[BACKEND_CONVERSATION, BACKEND_OPENAI],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        translation_key="backend",
                    )
                ),
                # --- conversation-agent backend ---
                vol.Optional(
                    CONF_CONVERSATION_AGENT,
                    description={
                        "suggested_value": opts.get(CONF_CONVERSATION_AGENT, "")
                    },
                ): selector.TextSelector(),
                vol.Required(
                    CONF_LANGUAGE, default=opts[CONF_LANGUAGE]
                ): selector.TextSelector(),
                # --- openai-compatible backend ---
                vol.Required(
                    CONF_API_BASE_URL, default=opts[CONF_API_BASE_URL]
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_API_KEY,
                    description={"suggested_value": opts.get(CONF_API_KEY, "")},
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(
                    CONF_MODEL, default=opts[CONF_MODEL]
                ): selector.TextSelector(),
                vol.Required(
                    CONF_SYSTEM_PROMPT, default=opts[CONF_SYSTEM_PROMPT]
                ): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
                vol.Required(
                    CONF_MAX_TOKENS, default=opts[CONF_MAX_TOKENS]
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=16, max=4096, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                # --- relay behaviour ---
                vol.Required(
                    CONF_TRIGGER_PHRASES, default=opts[CONF_TRIGGER_PHRASES]
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_TTS_ENTITY,
                    description={"suggested_value": opts.get(CONF_TTS_ENTITY)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player")
                ),
                vol.Required(
                    CONF_FIRST_TURN_TIMEOUT, default=opts[CONF_FIRST_TURN_TIMEOUT]
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5, max=4.5, step=0.1, mode=selector.NumberSelectorMode.SLIDER
                    )
                ),
                vol.Required(
                    CONF_BACKEND_TIMEOUT, default=opts[CONF_BACKEND_TIMEOUT]
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=300, step=5, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_GREETING, default=opts[CONF_GREETING]
                ): selector.TextSelector(),
                vol.Required(
                    CONF_THINKING_PHRASE, default=opts[CONF_THINKING_PHRASE]
                ): selector.TextSelector(),
                vol.Required(
                    CONF_ERROR_PHRASE, default=opts[CONF_ERROR_PHRASE]
                ): selector.TextSelector(),
                vol.Required(
                    CONF_END_SESSION, default=opts[CONF_END_SESSION]
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
