import json
from collections.abc import Callable

from app.ai.llm import LlmResponse, LlmUnavailableError


class FakeLlm:
    """Responde com o texto produzido por `reply(messages)`; registra cada chamada."""

    def __init__(self, reply: Callable[[list[dict]], str] | str, fail: bool = False) -> None:
        self._reply = reply
        self.fail = fail
        self.calls: list[dict] = []

    def complete(self, models, messages, *, zdr, json_mode, max_tokens, temperature):
        self.calls.append({"models": models, "messages": messages, "zdr": zdr})
        if self.fail:
            raise LlmUnavailableError("fake")
        content = self._reply(messages) if callable(self._reply) else self._reply
        return LlmResponse(content=content, model=models[0])


def json_reply(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)
