"""Ponto de entrada da Discloud, que procura o módulo `main` na raiz do projeto.

Serve tanto para `uvicorn main:app` quanto para `python main.py`.
"""

import uvicorn

from app.main import app

# O proxy da Discloud só encaminha para 0.0.0.0:8080.
DISCLOUD_HOST = "0.0.0.0"
DISCLOUD_PORT = 8080

__all__ = ["app"]

if __name__ == "__main__":
    uvicorn.run(app, host=DISCLOUD_HOST, port=DISCLOUD_PORT)
