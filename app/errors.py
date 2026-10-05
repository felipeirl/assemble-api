from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.i18n import EN, PT_BR, resolve_locale

STATUS_BY_CODE = {
    "invalid_request": 400,
    "unauthenticated": 401,
    "account_deactivated": 403,
    "not_found": 404,
    "nothing_to_undo": 409,
    "already_decided": 409,
    "nothing_to_regenerate": 409,
    "blocked_content": 422,
    "rate_limited": 429,
    "provider_unavailable": 503,
}

MESSAGES = {
    "invalid_request": {
        EN: "The request is invalid.",
        PT_BR: "A requisição é inválida.",
    },
    "unauthenticated": {
        EN: "Sign in again to continue.",
        PT_BR: "Entre novamente para continuar.",
    },
    "account_deactivated": {
        EN: "This account is deactivated.",
        PT_BR: "Esta conta está desativada.",
    },
    "not_found": {
        EN: "Not found.",
        PT_BR: "Não encontrado.",
    },
    "nothing_to_undo": {
        EN: "There is nothing to undo.",
        PT_BR: "Não há nada para desfazer.",
    },
    "nothing_to_regenerate": {
        EN: "There is no character reply to regenerate.",
        PT_BR: "Não há resposta do personagem para gerar de novo.",
    },
    "already_decided": {
        EN: "You have already decided on this character.",
        PT_BR: "Você já decidiu sobre este personagem.",
    },
    "blocked_content": {
        EN: "This message can't be sent.",
        PT_BR: "Esta mensagem não pode ser enviada.",
    },
    "rate_limited": {
        EN: "Too many messages. Try again later.",
        PT_BR: "Muitas mensagens. Tente novamente mais tarde.",
    },
    "provider_unavailable": {
        EN: "The service is temporarily unavailable. Try again.",
        PT_BR: "O serviço está temporariamente indisponível. Tente novamente.",
    },
}


class ApiError(Exception):
    def __init__(self, code: str, headers: dict[str, str] | None = None):
        if code not in STATUS_BY_CODE:
            raise ValueError(f"Código de erro desconhecido: {code}")
        super().__init__(code)
        self.code = code
        self.status = STATUS_BY_CODE[code]
        self.headers = headers


def error_response(
    request: Request, code: str, status: int, headers: dict[str, str] | None = None
) -> JSONResponse:
    locale = resolve_locale(request.headers.get("accept-language"))
    body = {"error": code, "message": MESSAGES[code][locale]}
    return JSONResponse(status_code=status, content=body, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc.code, exc.status, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        return error_response(request, "invalid_request", 400)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return error_response(request, "not_found", 404)
        return error_response(request, "invalid_request", exc.status_code)
