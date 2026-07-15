"""Tests for the NSFW output filter (NudeDetector integration)."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.services.nsfw_filter import (
    ContentRejected,
    NSFWFilterError,
    validate_batch_content,
    validate_image_content,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "nsfw"
SAFE_FIXTURE = FIXTURES_DIR / "safe-landscape.jpg"
EXPLICIT_FIXTURE = FIXTURES_DIR / "explicit-minimal.jpg"


def _image_bytes(path: Path) -> bytes:
    with open(path, "rb") as f:
        return f.read()


# ─── Real-image integration tests (require NudeDetector model) ───

pytestmark_model = pytest.mark.skipif(
    not os.environ.get("RUN_NSFW_MODEL_TESTS"),
    reason="Set RUN_NSFW_MODEL_TESTS=1 and pre-provision the NudeDetector model to run model-dependent tests",
)


@pytest.mark.nsfw_model
@pytest.mark.skipif(not SAFE_FIXTURE.exists(), reason="safe-landscape.jpg fixture not found")
def test_safe_image_passes_moderate():
    """A benign image should pass validation in moderate mode."""
    result = validate_image_content(_image_bytes(SAFE_FIXTURE), mode="moderate")
    assert result is True


@pytest.mark.nsfw_model
@pytest.mark.skipif(not EXPLICIT_FIXTURE.exists(), reason="explicit-minimal.jpg fixture not found")
def test_explicit_image_raises_content_rejected():
    """
    An image with explicit content should raise ContentRejected in moderate mode.
    NOTE: The current synthetic fixture does NOT trigger NudeDetector 3.4.2.
    This test will fail/skip until a suitable licensed real-image fixture is provided.
    """
    with pytest.raises(ContentRejected):
        validate_image_content(_image_bytes(EXPLICIT_FIXTURE), mode="moderate")


# ─── Fail-closed: corrupt / unprocessable input ───


def test_corrupt_bytes_raises_nsfw_filter_error():
    """Invalid image bytes should raise NSFWFilterError (fail-closed)."""
    with pytest.raises(NSFWFilterError):
        validate_image_content(b"not-a-real-image", mode="moderate")


def test_empty_bytes_raises_nsfw_filter_error():
    """Empty bytes should raise NSFWFilterError (fail-closed)."""
    with pytest.raises(NSFWFilterError):
        validate_image_content(b"", mode="moderate")


def test_validate_batch_content_fail_closed():
    """validate_batch_content should return (False, reason) on NSFWFilterError."""
    results, reasons = validate_batch_content([b"corrupt-data"], mode="moderate")
    assert results == [False]
    assert len(reasons) == 1
    assert reasons[0] != ""


# ─── Mock-based: policy and branch-level assertions ───


def _make_mock_detection(class_name: str, score: float):
    """Helper to create a mock detection dict resembling NudeDetector output."""
    return {"class": class_name, "score": score, "box": [0, 0, 10, 10]}


@patch("app.services.nsfw_filter._get_detector")
def test_moderate_rejects_explicit_label(mock_get_detector):
    """In moderate mode, an explicit label at threshold should be rejected."""
    mock_detector = MagicMock()
    mock_detector.detect.return_value = [
        _make_mock_detection("FEMALE_BREAST_EXPOSED", 0.60),
    ]
    mock_get_detector.return_value = mock_detector

    # Create a small real JPEG so PIL doesn't fail
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        Image.new("RGB", (100, 100), color="red").save(tmp.name, format="JPEG")
        img_bytes = _image_bytes(Path(tmp.name))
    os.unlink(tmp.name)

    with pytest.raises(ContentRejected) as exc_info:
        validate_image_content(img_bytes, threshold=0.6, mode="moderate")

    assert "confianza" in str(exc_info.value)


@patch("app.services.nsfw_filter._get_detector")
def test_moderate_accepts_suggestive_label(mock_get_detector):
    """
    In moderate mode, a suggestive-only label (not in explicit_categories)
    should NOT be rejected, even at the same score.
    """
    mock_detector = MagicMock()
    mock_detector.detect.return_value = [
        _make_mock_detection("BUTTOCKS_EXPOSED", 0.60),
    ]
    mock_get_detector.return_value = mock_detector

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        Image.new("RGB", (100, 100), color="red").save(tmp.name, format="JPEG")
        img_bytes = _image_bytes(Path(tmp.name))
    os.unlink(tmp.name)

    # Should pass without exception
    result = validate_image_content(img_bytes, threshold=0.6, mode="moderate")
    assert result is True


@patch("app.services.nsfw_filter._get_detector")
def test_strict_rejects_suggestive_label(mock_get_detector):
    """In strict mode, a suggestive label should be rejected above threshold * 1.2."""
    mock_detector = MagicMock()
    mock_detector.detect.return_value = [
        _make_mock_detection("BUTTOCKS_EXPOSED", 0.72),  # 0.6 * 1.2 = 0.72
    ]
    mock_get_detector.return_value = mock_detector

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        Image.new("RGB", (100, 100), color="red").save(tmp.name, format="JPEG")
        img_bytes = _image_bytes(Path(tmp.name))
    os.unlink(tmp.name)

    with pytest.raises(ContentRejected) as exc_info:
        validate_image_content(img_bytes, threshold=0.6, mode="strict")

    assert "sugestivo" in str(exc_info.value) or "confianza" in str(exc_info.value)


@patch("app.services.nsfw_filter._get_detector")
def test_detector_error_fails_closed(mock_get_detector):
    """If the detector raises an unexpected error, NSFWFilterError should be raised."""
    mock_detector = MagicMock()
    mock_detector.detect.side_effect = RuntimeError("model crashed")
    mock_get_detector.return_value = mock_detector

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        Image.new("RGB", (100, 100), color="red").save(tmp.name, format="JPEG")
        img_bytes = _image_bytes(Path(tmp.name))
    os.unlink(tmp.name)

    with pytest.raises(NSFWFilterError):
        validate_image_content(img_bytes, mode="moderate")


@patch("app.services.nsfw_filter._get_detector")
def test_batch_content_rejected(mock_get_detector):
    """validate_batch_content should return (False, reason) for ContentRejected."""
    mock_detector = MagicMock()
    mock_detector.detect.return_value = [
        _make_mock_detection("ANUS_EXPOSED", 0.80),
    ]
    mock_get_detector.return_value = mock_detector

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        Image.new("RGB", (100, 100), color="red").save(tmp.name, format="JPEG")
        img_bytes = _image_bytes(Path(tmp.name))
    os.unlink(tmp.name)

    results, reasons = validate_batch_content([img_bytes], mode="moderate")
    assert results == [False]
    assert len(reasons[0]) > 0


@patch("app.services.nsfw_filter._get_detector")
def test_moderate_accepts_clean_image(mock_get_detector):
    """With no detections, the image should pass."""
    mock_detector = MagicMock()
    mock_detector.detect.return_value = []
    mock_get_detector.return_value = mock_detector

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        Image.new("RGB", (100, 100), color="red").save(tmp.name, format="JPEG")
        img_bytes = _image_bytes(Path(tmp.name))
    os.unlink(tmp.name)

    result = validate_image_content(img_bytes, mode="moderate")
    assert result is True
