"""Ponto de entrada da Discloud, que procura o módulo `main` na raiz do projeto.

Serve tanto para `uvicorn main:app` quanto para `python main.py`.
"""

import os
from pathlib import Path

# Na Discloud o HOME aponta para "/", sem permissão de escrita: o Hugging Face não grava os pesos
# do Laya em /.cache e o guardrail não carrega. O cache vai para a pasta do projeto. Precisa vir
# antes de importar o app, porque o huggingface_hub lê o HF_HOME ao ser importado.
os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parent / ".cache" / "huggingface"))

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402

# O proxy da Discloud só encaminha para 0.0.0.0:8080.
DISCLOUD_HOST = "0.0.0.0"
DISCLOUD_PORT = 8080

__all__ = ["app"]

if __name__ == "__main__":
    uvicorn.run(app, host=DISCLOUD_HOST, port=DISCLOUD_PORT)
