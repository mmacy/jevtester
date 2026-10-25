from pathlib import Path

import pytest

import api_fixtures
from jevtester.preflight import preflight
from jevtester.spec import Capabilities, DecisionRequest, NoulQuestion, Target

WORKERS = api_fixtures.CONFIG.targets["clef-flash@workers-ai"]
PNG = b"\x89PNG\r\n\x1a\n"
JPEG = b"\xff\xd8\xff\xe0"
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 "
GIF = b"GIF89a"


def image_target(limits: dict[str, object]) -> Target:
    capabilities = Capabilities.model_validate({"images": True, **limits})
    return WORKERS.model_copy(update={"capabilities": capabilities})


def write(path: Path, header: bytes, size: int) -> str:
    path.write_bytes(header + b"\x00" * (size - len(header)))
    return str(path)


def request_with(images: list[str]) -> DecisionRequest:
    return DecisionRequest(state="s", questions={"q": NoulQuestion(instructions="?")}, images=images)


def test_images_within_every_limit_pass(tmp_path: Path) -> None:
    target = image_target({"max_image_bytes": 100, "max_total_image_bytes": 250, "image_formats": ["png", "jpeg"]})
    images = [write(tmp_path / "a.png", PNG, 100), write(tmp_path / "b.jpg", JPEG, 100)]
    assert preflight(request_with(images), target) == (None, [])


def test_an_image_over_the_size_limit_is_rejected(tmp_path: Path) -> None:
    target = image_target({"max_image_bytes": 100})
    error, _ = preflight(request_with([write(tmp_path / "a.png", PNG, 101)]), target)
    assert error is not None
    assert error.code == "preflight"
    assert error.message == f"{tmp_path / 'a.png'} is 101 bytes, over the limit of 100."


def test_images_over_the_total_size_limit_are_rejected(tmp_path: Path) -> None:
    target = image_target({"max_image_bytes": 100, "max_total_image_bytes": 150})
    images = [write(tmp_path / "a.png", PNG, 100), write(tmp_path / "b.png", PNG, 51)]
    error, _ = preflight(request_with(images), target)
    assert error is not None
    assert error.code == "preflight"
    assert error.message == "The images total 151 bytes, over the limit of 150."


@pytest.mark.parametrize(
    ("header", "detected"),
    [(GIF, "an unknown format"), (WEBP, "webp")],
)
def test_an_image_in_a_format_the_target_does_not_accept_is_rejected(
    tmp_path: Path, header: bytes, detected: str
) -> None:
    target = image_target({"image_formats": ["png", "jpeg"]})
    path = write(tmp_path / "a.png", header, 20)
    error, _ = preflight(request_with([path]), target)
    assert error is not None
    assert error.code == "preflight"
    assert error.message == f"{path} is {detected}. {WORKERS.name} accepts png and jpeg."


def test_every_format_passes_when_the_target_lists_none(tmp_path: Path) -> None:
    error, _ = preflight(request_with([write(tmp_path / "a.gif", GIF, 20)]), image_target({}))
    assert error is None


def test_an_image_that_cannot_be_read_is_rejected(tmp_path: Path) -> None:
    missing = str(tmp_path / "missing.png")
    error, _ = preflight(request_with([missing]), image_target({"max_image_bytes": 100}))
    assert error is not None
    assert error.code == "preflight"
    assert error.message.startswith(f"Can't read {missing}")
