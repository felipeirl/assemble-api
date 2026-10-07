import json
from collections.abc import Callable

from app.ai.guardrail import ALLOWED, GuardrailUnavailableError, GuardVerdict
from app.ai.llm import LlmResponse, LlmUnavailableError

DEFAULT_SUGGESTIONS = ["Como é voar?", "Qual sua missão?", "Algum conselho?"]


class FakeQueue:
    """Fila dos testes: roda a tarefa na hora ou, com `hold`, guarda para `run_pending`."""

    def __init__(self, capacity: int | None = None) -> None:
        self.capacity = capacity
        self.hold = False
        self.pending: list[Callable[[], None]] = []

    def submit(self, task: Callable[[], None]) -> bool:
        if self.capacity is not None and len(self.pending) >= self.capacity:
            return False
        if self.hold:
            self.pending.append(task)
        else:
            task()
        return True

    def run_pending(self) -> None:
        tasks, self.pending = self.pending, []
        for task in tasks:
            task()

    def wait_idle(self) -> None:
        self.run_pending()


class FakeLlm:
    """Responde com o texto produzido por `reply(messages)`; registra cada chamada."""

    def __init__(self, reply: Callable[[list[dict]], str] | str, fail: bool = False) -> None:
        self._reply = reply
        self.fail = fail
        self.calls: list[dict] = []

    def complete(
        self,
        models,
        messages,
        *,
        zdr,
        json_mode,
        max_tokens,
        temperature,
        timeout=None,
        stream=False,
        reasoning_efforts=None,
    ):
        self.calls.append(
            {
                "models": models,
                "messages": messages,
                "zdr": zdr,
                "reasoning_efforts": reasoning_efforts,
            }
        )
        if self.fail:
            raise LlmUnavailableError("fake")
        content = self._reply(messages) if callable(self._reply) else self._reply
        return LlmResponse(content=content, model=models[0])


def json_reply(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def chat_reply(messages: list[dict]) -> str:
    # A nota interna de condução vai na mesma mensagem do usuário; a resposta ecoa só o texto dele.
    last = messages[-1]["content"].split("\n\n(Internal note")[0]
    return json_reply({"reply": f"Resposta a: {last[:40]}", "suggestions": DEFAULT_SUGGESTIONS})


class FakeGuardrail:
    """Bloqueia por palavras-gatilho; `affinity_value` alimenta a decisão de match."""

    INPUT_TRIGGERS = {
        "jailbreak": "jailbreak",
        "suicid": "self_harm",
        "@": "personal_data",
        "sexo": "sexual",
    }
    OUTPUT_TRIGGERS = {"canônico": "canon_claim", "sou uma IA": "out_of_role"}
    SOURCE_TRIGGERS = {"IGNORE PREVIOUS": "injection"}

    def __init__(self, affinity_value: float = 0.5, unavailable: bool = False) -> None:
        self.affinity_value = affinity_value
        self.unavailable = unavailable
        self.checked: list[tuple[str, str]] = []

    def check_input(self, text):
        return self._check("input", text, self.INPUT_TRIGGERS)

    def check_output(self, text):
        return self._check("output", text, self.OUTPUT_TRIGGERS)

    def check_source(self, text):
        return self._check("source", text, self.SOURCE_TRIGGERS)

    def affinity(self, user_profile, persona):
        self._raise_if_unavailable()
        return self.affinity_value

    def _check(self, kind, text, triggers):
        self._raise_if_unavailable()
        self.checked.append((kind, text))
        for trigger, reason in triggers.items():
            if trigger in text:
                return GuardVerdict(blocked=True, reason=reason)
        return ALLOWED

    def _raise_if_unavailable(self):
        if self.unavailable:
            raise GuardrailUnavailableError("fake")
