"""Teste de carga do chat: quantos usuários conversando ao mesmo tempo a API aguenta.

Sobe a API de verdade (uvicorn) num processo só, com o Laya real e o modelo de linguagem simulado
com latência fixa, e faz N usuários conversarem em paralelo. Mede quanto cada resposta leva do
envio até o servidor gravar a resposta do personagem.

    uv run python scripts/load_test.py --users 20 --seconds 120 --question-ms 400

`--question-ms` faz cada pergunta ao Laya levar pelo menos esse tempo, para imitar a CPU da
Discloud (cerca de 330 a 410 ms por pergunta; no PC de desenvolvimento, uns 140 ms).
"""

import argparse
import logging
import random
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field

import httpx
import uvicorn

from app.ai.guardrail import LayaGuardrail, build_laya_router
from app.config import Settings
from app.container import Container
from app.main import create_app
from app.store.memory import MemoryStore
from tests.conftest import FakeTokenVerifier
from tests.factories import seed_characters, seed_user
from tests.fakes import FakeLlm, chat_reply

PORT = 8765
CHARACTER = "storm"
MESSAGES = (
    "Oi! Como foi o seu dia?",
    "Qual foi a missão mais difícil que você já teve?",
    "Você tem medo de alguma coisa?",
    "Me conta uma curiosidade sobre os X-Men.",
    "O que você faz quando não está salvando o mundo?",
)
POLL_SECONDS = 0.2
ANSWER_TIMEOUT_SECONDS = 120


class SlowRouter:
    """O Laya real, com um piso de tempo por pergunta (imita uma CPU mais fraca)."""

    def __init__(self, router, question_ms: float) -> None:
        self._router = router
        self._question_seconds = question_ms / 1000

    def predict(self, state, questions, model=None):
        start = time.perf_counter()
        result = self._router.predict(state, questions, model=model)
        wait = self._question_seconds * len(questions) - (time.perf_counter() - start)
        if wait > 0:
            time.sleep(wait)
        return result


@dataclass
class Report:
    latencies: list[float] = field(default_factory=list)
    failures: int = 0
    rejected: dict[int, int] = field(default_factory=dict)
    sent: int = 0


def build_container(args: argparse.Namespace) -> Container:
    settings = Settings(
        _env_file=None,
        jobs_key="load-test",
        chat_model="chat-main",
        chat_fallback_model="chat-reserve",
        match_cutoff=0.0,
        messages_per_hour=100_000,
        assembles_per_hour=100_000,
    )
    if args.workers:
        settings.chat_reply_workers = args.workers

    def slow_llm(messages: list[dict]) -> str:
        time.sleep(args.llm_seconds)
        return chat_reply(messages)

    guardrail = LayaGuardrail(
        threshold=settings.guardrail_threshold,
        router_factory=lambda: SlowRouter(build_laya_router(), args.question_ms),
    )
    from app.clock import Clock

    return Container(
        settings=settings,
        store=MemoryStore(),
        token_verifier=FakeTokenVerifier(),
        clock=Clock(),
        llm=FakeLlm(slow_llm),
        guardrail=guardrail,
    )


def start_server(container: Container) -> None:
    config = uvicorn.Config(
        create_app(lambda: container), host="127.0.0.1", port=PORT, log_level="warning"
    )
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, name="uvicorn", daemon=True).start()
    for _ in range(100):
        if server.started:
            return
        time.sleep(0.1)
    raise RuntimeError("o servidor não subiu")


def messages_of(container: Container, uid: str) -> list[dict]:
    docs = container.store.query(f"users/{uid}/matches/{CHARACTER}/messages")
    return [doc for _, doc in docs]


def pending_count(container: Container, uid: str) -> int:
    return sum(1 for doc in messages_of(container, uid) if doc.get("status") == "pending")


def run_user(
    container: Container,
    uid: str,
    args: argparse.Namespace,
    deadline: float,
    report: Report,
    guard: threading.Lock,
) -> None:
    headers = {"Authorization": f"Bearer token-{uid}", "Accept-Language": "pt-BR"}
    rng = random.Random(uid)
    with httpx.Client(base_url=f"http://127.0.0.1:{PORT}", headers=headers, timeout=60) as client:
        time.sleep(rng.uniform(0, args.think_seconds))  # os usuários não começam juntos
        while time.perf_counter() < deadline:
            sent_at = time.perf_counter()
            response = client.post(
                f"/v2/connections/{CHARACTER}/messages",
                json={"text": rng.choice(MESSAGES)},
                headers={"Idempotency-Key": f"{uid}-{time.time_ns()}"},
            )
            with guard:
                report.sent += 1
            if response.status_code != 202:
                with guard:
                    report.rejected[response.status_code] = (
                        report.rejected.get(response.status_code, 0) + 1
                    )
                time.sleep(2)
                continue
            if wait_for_answer(container, uid, sent_at):
                with guard:
                    report.latencies.append(time.perf_counter() - sent_at)
            else:
                with guard:
                    report.failures += 1
            time.sleep(rng.uniform(args.think_seconds * 0.5, args.think_seconds * 1.5))


def wait_for_answer(container: Container, uid: str, sent_at: float) -> bool:
    while time.perf_counter() - sent_at < ANSWER_TIMEOUT_SECONDS:
        if pending_count(container, uid) == 0:
            return True
        time.sleep(POLL_SECONDS)
    return False


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--seconds", type=int, default=90)
    parser.add_argument(
        "--think-seconds", type=float, default=20, help="pausa média entre mensagens"
    )
    parser.add_argument("--llm-seconds", type=float, default=6, help="latência do modelo simulado")
    parser.add_argument("--question-ms", type=float, default=0, help="piso por pergunta do Laya")
    parser.add_argument("--workers", type=int, default=0, help="consumidores da fila do chat")
    args = parser.parse_args()

    logging.getLogger().setLevel(logging.WARNING)
    container = build_container(args)
    seed_characters(container.store)
    start_server(container)
    print("aquecendo o Laya...", flush=True)
    container.guardrail.warm_up()

    uids = [f"load-{index}" for index in range(args.users)]
    with httpx.Client(base_url=f"http://127.0.0.1:{PORT}", timeout=120) as client:
        for uid in uids:
            seed_user(container.store, uid)
            auth = {"Authorization": f"Bearer token-{uid}", "X-Timezone": "America/Sao_Paulo"}
            body = {"characterId": CHARACTER, "choice": "ASSEMBLE"}
            client.post("/v2/decisions", json=body, headers=auth)
    container.assemble_queue.wait_idle()

    report = Report()
    guard = threading.Lock()
    deadline = time.perf_counter() + args.seconds
    print(
        f"{args.users} usuários, {args.seconds} s, pausa ~{args.think_seconds:.0f} s, "
        f"modelo {args.llm_seconds:.0f} s, Laya >= {args.question_ms:.0f} ms/pergunta",
        flush=True,
    )
    threads = [
        threading.Thread(target=run_user, args=(container, uid, args, deadline, report, guard))
        for uid in uids
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    print_report(report, args)
    sys.exit(0)


def print_report(report: Report, args: argparse.Namespace) -> None:
    done = len(report.latencies)
    per_minute = done / (args.seconds / 60)
    print(
        f"\nmensagens enviadas: {report.sent}, respondidas: {done}, sem resposta: {report.failures}"
    )
    if report.rejected:
        print(f"recusadas pelo servidor: {report.rejected}")
    if done:
        lat = report.latencies
        print(
            f"tempo até a resposta: mediana {statistics.median(lat):.1f} s, "
            f"p95 {percentile(lat, 0.95):.1f} s, máximo {max(lat):.1f} s"
        )
    print(f"vazão: {per_minute:.1f} respostas por minuto")


if __name__ == "__main__":
    main()
