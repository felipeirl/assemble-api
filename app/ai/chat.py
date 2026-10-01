"""Módulo de IA do chat (seção 10): sem estado; recebe persona, histórico e mensagem."""

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from app.ai import prompts
from app.ai.guardrail import REASON_SELF_HARM, Guardrail
from app.ai.llm import InvalidModelOutputError, LlmClient, parse_json_object
from app.catalog.text import truncate

CHAT_MAX_TOKENS = 400
CHAT_TEMPERATURE = 0.8
FIXED_REPLY_MODEL = "fixed"
CHARACTER_FACT_KEYS = ("id", "name", "realName", "origin", "powers", "teams", "firstAppearance")

logger = logging.getLogger(__name__)


class BlockedInputError(Exception):
    """Mensagem do usuário recusada pelo guardrail antes de chegar ao modelo."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ChatRequest:
    request_id: str
    mode: Literal["opener", "reply"]
    locale: str
    character: dict[str, Any]
    persona: dict[str, Any]
    history: list[dict[str, str]] = field(default_factory=list)
    message: str = ""


@dataclass(frozen=True)
class ChatResult:
    reply: str
    suggestions: list[str]
    blocked: bool
    block_reason: str | None
    model: str
    prompt_version: str


def character_context(character_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    """Bloco `character` da interface 10.1, a partir do documento de `characters/`."""
    context = {"id": character_id, **{k: doc[k] for k in CHARACTER_FACT_KEYS[1:] if doc.get(k)}}
    if doc.get("bio"):
        context["summary"] = truncate(doc["bio"], prompts.SUMMARY_MAX_CHARS)
    context["source"] = doc.get("source", "Comic Vine")
    return context


class ChatEngine:
    def __init__(self, llm: LlmClient, guardrail: Guardrail, models: list[str]) -> None:
        self._llm = llm
        self._guardrail = guardrail
        self._models = models

    def respond(self, request: ChatRequest) -> ChatResult:
        """Levanta BlockedInputError, LlmUnavailableError ou GuardrailUnavailableError."""
        if request.mode == "reply":
            verdict = self._guardrail.check_input(request.message)
            if verdict.blocked and verdict.reason == REASON_SELF_HARM:
                return self._fixed(request, prompts.SELF_HARM_REPLY, REASON_SELF_HARM)
            if verdict.blocked:
                raise BlockedInputError(verdict.reason or "blocked")

        response = self._llm.complete(
            self._models,
            self._messages(request),
            zdr=True,
            json_mode=True,
            max_tokens=CHAT_MAX_TOKENS,
            temperature=CHAT_TEMPERATURE,
        )
        reply, suggestions = parse_reply(response.content)
        if not reply:
            raise InvalidModelOutputError("Resposta vazia")

        output = self._guardrail.check_output(reply)
        if output.blocked:
            return self._fixed(request, prompts.SAFE_REPLY, output.reason, model=response.model)
        if len(suggestions) != prompts.SUGGESTION_COUNT:
            suggestions = prompts.fallback_suggestions(request.character, request.locale)
        return ChatResult(
            reply=reply,
            suggestions=suggestions,
            blocked=False,
            block_reason=None,
            model=response.model,
            prompt_version=prompts.PROMPT_VERSION,
        )

    def _messages(self, request: ChatRequest) -> list[dict[str, str]]:
        facts = {k: v for k, v in request.character.items() if k != "summary"}
        summary = self._trusted_summary(request.character.get("summary"))
        system = "\n\n".join(
            [
                prompts.system_prompt(request.locale),
                prompts.character_block(facts, summary),
                prompts.persona_block(request.persona),
            ]
        )
        messages = [{"role": "system", "content": system}]
        for item in request.history:
            role = "user" if item["role"] == "user" else "assistant"
            messages.append({"role": role, "content": item["text"]})
        if request.mode == "opener":
            messages.append(
                {"role": "user", "content": prompts.opener_instruction(request.character["name"])}
            )
        else:
            messages.append({"role": "user", "content": request.message})
        return messages

    def _trusted_summary(self, summary: str | None) -> str | None:
        """O resumo da fonte (wiki editável) só entra no prompt se o guardrail aprovar."""
        if not summary:
            return None
        if self._guardrail.check_source(summary).blocked:
            logger.info("Resumo da fonte descartado pelo guardrail.")
            return None
        return summary

    def _fixed(
        self,
        request: ChatRequest,
        replies: dict[str, str],
        reason: str | None,
        model: str = FIXED_REPLY_MODEL,
    ) -> ChatResult:
        return ChatResult(
            reply=replies[request.locale],
            suggestions=prompts.fallback_suggestions(request.character, request.locale),
            blocked=True,
            block_reason=reason,
            model=model,
            prompt_version=prompts.PROMPT_VERSION,
        )


def parse_reply(content: str) -> tuple[str, list[str]]:
    """Lê {"reply", "suggestions"}; texto fora de JSON vira a própria resposta."""
    try:
        data = parse_json_object(content)
    except InvalidModelOutputError:
        return content.strip(), []
    reply = str(data.get("reply") or "").strip()
    raw = data.get("suggestions")
    suggestions = [
        str(item).strip()[: prompts.SUGGESTION_MAX_CHARS]
        for item in (raw if isinstance(raw, list) else [])
        if str(item).strip()
    ]
    return reply, suggestions[: prompts.SUGGESTION_COUNT]
