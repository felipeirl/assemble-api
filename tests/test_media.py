import hashlib
from datetime import timedelta

import httpx
import pytest

from app.media import AVATAR_TRANSFORMATION, FOLDER, CloudinaryPhotos, sign
from app.services.account import GRACE_PERIOD
from tests.conftest import auth_header
from tests.factories import seed_user

UID = "u1"
HEADERS = auth_header(UID)


class RecordingPost:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail = fail

    def __call__(self, url, data, timeout):
        self.calls.append((url, data))
        if self.fail:
            raise httpx.ConnectError("sem rede")
        return httpx.Response(200, json={"result": "ok"}, request=httpx.Request("POST", url))


@pytest.fixture
def photos(container, clock):
    post = RecordingPost()
    container.photos = CloudinaryPhotos("demo", "key123", "s3cr3t", clock, post=post)
    container.photos.recorder = post
    return container.photos


def test_signature_follows_the_cloudinary_algorithm():
    params = {"timestamp": "1700000000", "public_id": "u1", "folder": "f"}

    expected = hashlib.sha1(b"folder=f&public_id=u1&timestamp=1700000000s3cr3t").hexdigest()

    assert sign(params, "s3cr3t") == expected


def test_the_signed_upload_is_locked_to_the_user_and_the_transformation(client, photos, clock):
    response = client.post("/v2/me/photo/signature", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["uploadUrl"] == "https://api.cloudinary.com/v1_1/demo/image/upload"
    fields = body["fields"]
    assert fields["public_id"] == UID and fields["folder"] == FOLDER
    assert fields["transformation"] == AVATAR_TRANSFORMATION
    assert fields["timestamp"] == str(int(clock.now().timestamp()))
    assert fields["api_key"] == "key123"
    signed = {k: v for k, v in fields.items() if k not in ("api_key", "signature")}
    assert fields["signature"] == sign(signed, "s3cr3t")
    assert "s3cr3t" not in response.text


def test_without_cloudinary_settings_the_route_is_unavailable(client, container):
    response = client.post("/v2/me/photo/signature", headers=HEADERS)

    assert response.status_code == 503
    assert response.json()["error"] == "provider_unavailable"


def test_the_photo_is_deleted_from_cloudinary_when_the_account_is_purged(container, photos, clock):
    seed_user(container.store, UID)
    container.users.deactivate(UID, clock.now() - GRACE_PERIOD - timedelta(days=1))

    container.account_service.purge()

    url, data = photos.recorder.calls[0]
    assert url == "https://api.cloudinary.com/v1_1/demo/image/destroy"
    assert data["public_id"] == f"{FOLDER}/{UID}"
    assert container.store.get(f"users/{UID}") is None


def test_a_cloudinary_failure_does_not_block_the_account_purge(container, clock):
    container.photos = CloudinaryPhotos("demo", "k", "s", clock, post=RecordingPost(fail=True))
    seed_user(container.store, UID)
    container.users.deactivate(UID, clock.now() - GRACE_PERIOD - timedelta(days=1))

    report = container.account_service.purge()

    assert report.accounts_deleted == [UID]
