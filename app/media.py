"""Foto do perfil no Cloudinary: o app envia o arquivo direto, com uma assinatura feita aqui.

O segredo da API nunca sai do servidor. A assinatura vale só para o `public_id` do próprio
usuário, com a transformação (recorte quadrado de 256 px em JPEG) já fixada nos parâmetros
assinados, então o app não consegue enviar outra coisa nem sobrescrever a foto de outra pessoa.
"""

import hashlib
import logging
from collections.abc import Callable
from typing import Any

import httpx

from app.clock import Clock

UPLOAD_URL = "https://api.cloudinary.com/v1_1/{cloud}/image/upload"
DESTROY_URL = "https://api.cloudinary.com/v1_1/{cloud}/image/destroy"
FOLDER = "assemble/avatars"
AVATAR_TRANSFORMATION = "c_fill,g_face,w_256,h_256,f_jpg,q_auto"
DESTROY_TIMEOUT_SECONDS = 15.0

logger = logging.getLogger(__name__)


def sign(params: dict[str, str], api_secret: str) -> str:
    """Assinatura do Cloudinary: SHA-1 dos parâmetros em ordem alfabética mais o segredo."""
    to_sign = "&".join(f"{key}={params[key]}" for key in sorted(params))
    return hashlib.sha1((to_sign + api_secret).encode("utf-8")).hexdigest()  # noqa: S324


class CloudinaryPhotos:
    def __init__(
        self,
        cloud_name: str,
        api_key: str,
        api_secret: str,
        clock: Clock,
        post: Callable[..., Any] = httpx.post,
    ) -> None:
        self._cloud = cloud_name
        self._api_key = api_key
        self._api_secret = api_secret
        self._clock = clock
        self._post = post

    def _timestamp(self) -> str:
        return str(int(self._clock.now().timestamp()))

    def upload_signature(self, uid: str) -> tuple[str, dict[str, str]]:
        """URL de envio e campos do formulário (assinados) para a foto de [uid]."""
        params = {
            "folder": FOLDER,
            "public_id": uid,
            "overwrite": "true",
            "invalidate": "true",
            "transformation": AVATAR_TRANSFORMATION,
            "timestamp": self._timestamp(),
        }
        fields = {**params, "api_key": self._api_key, "signature": sign(params, self._api_secret)}
        return UPLOAD_URL.format(cloud=self._cloud), fields

    def destroy(self, uid: str) -> None:
        """Apaga a foto de [uid]; não levanta: foto órfã não pode travar a exclusão da conta."""
        params = {
            "public_id": f"{FOLDER}/{uid}",
            "invalidate": "true",
            "timestamp": self._timestamp(),
        }
        data = {**params, "api_key": self._api_key, "signature": sign(params, self._api_secret)}
        try:
            response = self._post(
                DESTROY_URL.format(cloud=self._cloud), data=data, timeout=DESTROY_TIMEOUT_SECONDS
            )
            response.raise_for_status()
        except httpx.HTTPError:
            logger.warning("Não foi possível apagar a foto de %s no Cloudinary.", uid)
