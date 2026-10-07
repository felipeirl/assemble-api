"""Módulo de IA do chat (seção 10): sem estado; recebe persona, histórico e mensagem."""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.ai import prompts
from app.ai.guardrail import REASON_SELF_HARM, REASON_SEXUAL_VIOLENCE, Guardrail
from app.ai.llm import InvalidModelOutputError, LlmClient, parse_json_object
from app.ai.memory import memory_block
from app.catalog.names import display_name
from app.catalog.text import truncate
from app.timing import timed

# Folga para o caso de o modelo raciocinar um pouco: o raciocínio também conta no limite.
CHAT_MAX_TOKENS = 400
CHAT_TEMPERATURE = 0.8
GENERATION_ATTEMPTS = 3
FIXED_REPLY_MODEL = "fixed"
CHARACTER_FACT_KEYS = ("id", "name", "realName", "origin", "powers", "teams", "firstAppearance")

# Resposta fixa de acolhimento por motivo: o modelo não é chamado e o texto não é guardado.
REFERRAL_REPLIES = {
    REASON_SELF_HARM: prompts.SELF_HARM_REPLY,
    REASON_SEXUAL_VIOLENCE: prompts.SEXUAL_VIOLENCE_REPLY,
}

REPLY_FIELD_PATTERN = re.compile(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"')

logger = logging.getLogger(__name__)


class BlockedInputError(Exception):
    """Mensagem do usuário recusada pelo guardrail antes de chegar ao modelo."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class UserContext:
    """O que o app sabe do usuário, para o personagem usar sem dizer que sabe.

    `first_name` já vem limpo; `bio` e `looking_for` são texto livre e passam pelo guardrail antes
    de entrar no prompt; `preferences` e `in_common` vêm de enums do app.
    """

    first_name: str | None = None
    bio: str | None = None
    looking_for: str | None = None
    preferences: dict[str, list[str]] = field(default_factory=dict)
    in_common: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChatRequest:
    request_id: str
    mode: Literal["opener", "reply"]
    locale: str
    character: dict[str, Any]
    persona: dict[str, Any]
    history: list[dict[str, str]] = field(default_factory=list)
    message: str = ""
    # O que o app sabe do usuário (perfil, preferências e o que tem em comum com o personagem).
    user: UserContext | None = None
    # Resumo do que saiu da janela de histórico (app/ai/memory.py).
    memory: str | None = None


@dataclass(frozen=True)
class ChatResult:
    reply: str
    suggestions: list[str]
    blocked: bool
    block_reason: str | None
    model: str
    prompt_version: str


def character_context(character_id: str, doc: dict[str, Any], locale: str = "en") -> dict[str, Any]:
    """Bloco `character` da interface 10.1, a partir do documento de `characters/`."""
    context = {"id": character_id, **{k: doc[k] for k in CHARACTER_FACT_KEYS[1:] if doc.get(k)}}
    context["name"] = display_name(character_id, doc["name"], locale)
    if doc.get("bio"):
        context["summary"] = truncate(doc["bio"], prompts.SUMMARY_MAX_CHARS)
    context["source"] = doc.get("source", "Comic Vine")
    return context


class ChatEngine:
    def __init__(
        self,
        llm: LlmClient,
        guardrail: Guardrail,
        models: list[str],
        reasoning_efforts: dict[str, str] | None = None,
    ) -> None:
        self._llm = llm
        self._guardrail = guardrail
        self._models = models
        self._reasoning_efforts = reasoning_efforts or {}

    def respond(self, request: ChatRequest) -> ChatResult:
        """Levanta BlockedInputError, LlmUnavailableError ou GuardrailUnavailableError."""
        if request.mode == "reply":
            with timed("filtro de entrada"):
                verdict = self._guardrail.check_input(request.message)
            if verdict.blocked and verdict.reason in REFERRAL_REPLIES:
                return self._fixed(request, REFERRAL_REPLIES[verdict.reason], verdict.reason)
            if verdict.blocked:
                raise BlockedInputError(verdict.reason or "blocked")

        response, reply, suggestions = self._generate(request)

        with timed("filtro de saida"):
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

    def _generate(self, request: ChatRequest) -> tuple[Any, str, list[str]]:
        """Chama o modelo; uma resposta sem texto (formato errado) é pedida de novo uma vez."""
        for attempt in range(GENERATION_ATTEMPTS):
            with timed(f"modelo (tentativa {attempt + 1})"):
                response = self._llm.complete(
                    self._models,
                    self._messages(request),
                    zdr=True,
                    json_mode=True,
                    max_tokens=CHAT_MAX_TOKENS,
                    temperature=CHAT_TEMPERATURE,
                    reasoning_efforts=self._reasoning_efforts,
                )
            reply, suggestions = parse_reply(response.content)
            if reply:
                return response, reply, suggestions
            logger.info("Resposta sem texto (tentativa %d).", attempt + 1)
        raise InvalidModelOutputError("Resposta vazia")

    def _messages(self, request: ChatRequest) -> list[dict[str, str]]:
        facts = {k: v for k, v in request.character.items() if k != "summary"}
        summary = self._trusted_summary(request.character.get("summary"))
        system = "\n\n".join(
            [
                prompts.system_prompt(request.locale),
                prompts.character_block(facts, summary),
                prompts.persona_block(request.persona),
                *self._user_blocks(request.user),
                *([memory_block(request.memory)] if request.memory else []),
            ]
        )
        messages = [{"role": "system", "content": system}]
        for item in request.history:
            role = "user" if item["role"] == "user" else "assistant"
            messages.append({"role": role, "content": item["text"]})
        if request.mode == "opener":
            looking_for = self._trusted_user_text(
                request.user.looking_for if request.user else None
            )
            instruction = prompts.opener_instruction(request.character["name"], looking_for)
            messages.append({"role": "user", "content": instruction})
        else:
            note = prompts.conversation_move(request.history, request.message)
            messages.append({"role": "user", "content": f"{request.message}\n\n{note}"})
        return messages

    def _user_blocks(self, user: UserContext | None) -> list[str]:
        """Bloco com o que o app sabe do usuário; vazio quando não há nada a dizer."""
        if user is None:
            return []
        notes: dict[str, Any] = {
            "firstName": user.first_name,
            "bio": self._trusted_user_text(user.bio),
            "lookingForInAConversation": self._trusted_user_text(user.looking_for),
            "likes": user.preferences or None,
            "inCommonWithYou": user.in_common or None,
        }
        notes = {key: value for key, value in notes.items() if value}
        return [prompts.user_block(notes)] if notes else []

    def _trusted_summary(self, summary: str | None) -> str | None:
        """O resumo da fonte (wiki editável) só entra no prompt se o guardrail aprovar."""
        if not summary:
            return None
        if self._guardrail.check_source(summary).blocked:
            logger.info("Resumo da fonte descartado pelo guardrail.")
            return None
        return summary

    def _trusted_user_text(self, text: str | None) -> str | None:
        """Texto do perfil do usuário só entra no prompt se o guardrail aprovar."""
        if not text:
            return None
        if self._guardrail.check_source(text).blocked:
            logger.info("Frase do perfil descartada pelo guardrail.")
            return None
        return text

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
        # JSON quebrado: o texto da resposta ainda pode ser lido, o resto não vai ao usuário.
        match = REPLY_FIELD_PATTERN.search(content)
        if match:
            return json.loads(f'"{match.group(1)}"'), []
        return ("" if content.lstrip().startswith(("[", "{")) else content.strip()), []
    reply = data.get("reply")
    reply = reply.strip() if isinstance(reply, str) else ""
    raw = data.get("suggestions")
    suggestions = [
        str(item).strip()[: prompts.SUGGESTION_MAX_CHARS]
        for item in (raw if isinstance(raw, list) else [])
        if str(item).strip()
    ]
    return reply, suggestions[: prompts.SUGGESTION_COUNT]
