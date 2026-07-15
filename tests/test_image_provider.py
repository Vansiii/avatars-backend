"""Tests for the Pollinations image provider."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from app.services.image_provider import generate_image


@pytest.mark.asyncio
async def test_generate_image_sends_safe_true():
    """The provider must send safe='true' in the Pollinations GET request."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "image/jpeg"}
    mock_response.content = b"fake-image-bytes"

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("app.services.image_provider.httpx.AsyncClient", return_value=mock_client):
        result = await generate_image("a test prompt", width=512, height=512)

    assert result == b"fake-image-bytes"

    mock_client.get.assert_awaited_once()
    call_kwargs = mock_client.get.call_args.kwargs
    params = call_kwargs.get("params", {})

    assert params.get("safe") == "true", (
        f"Expected safe='true' in request params, got safe={params.get('safe')!r}"
    )
    assert params.get("nologo") == "true"
    assert params.get("private") == "true"


@pytest.mark.asyncio
async def test_generate_image_nsfw_rejected():
    """A 4xx blocking response from Pollinations should raise NSFWRejected."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 400
    mock_response.headers = {"content-type": "text/plain"}

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_response)

    with (
        patch("app.services.image_provider.httpx.AsyncClient", return_value=mock_client),
        pytest.raises(Exception) as exc_info,
    ):
        await generate_image("nsfw-prompt")

    msg = str(exc_info.value).lower()
    assert "rechazado" in msg or "contenido" in msg


@pytest.mark.asyncio
async def test_generate_image_provider_error():
    """A 5xx or unexpected response should raise ProviderError after retries."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 500
    mock_response.headers = {"content-type": "text/plain"}

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_response)

    with (
        patch("app.services.image_provider.httpx.AsyncClient", return_value=mock_client),
        pytest.raises(Exception) as exc_info,
    ):
        await generate_image("fail-prompt")

    class_name = exc_info.type.__name__
    msg = str(exc_info.value).lower()
    assert "ProviderError" in class_name or "proveedor" in msg or "fallo" in msg


@pytest.mark.asyncio
async def test_generate_image_request_error_retries():
    """A network error should retry and eventually raise ProviderError."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(side_effect=httpx.RequestError("connection failed"))

    with (
        patch("app.services.image_provider.httpx.AsyncClient", return_value=mock_client),
        pytest.raises(Exception) as exc_info,
    ):
        await generate_image("retry-prompt")

    class_name = exc_info.type.__name__
    msg = str(exc_info.value).lower()
    assert "ProviderError" in class_name or "fallo" in msg or "proveedor" in msg
