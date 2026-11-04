from varde_code import ApiError, CaptureInput
from varde_code.toz_bridge import capture_text


def test_capture_input_factories_preserve_capture_payloads() -> None:
    assert CaptureInput.from_text("hello") == CaptureInput(text="hello")
    assert CaptureInput.from_items(["one", "two"]) == CaptureInput(items=("one", "two"))


def test_api_error_keeps_machine_code_and_human_message() -> None:
    error = ApiError.not_found("file.py")

    assert error.code == "not_found"
    assert error.message == "not found: file.py"
    assert str(error) == "not_found: not found: file.py"


def test_capture_text_passes_capture_input_to_provider() -> None:
    class Provider:
        def capture(self, input: CaptureInput, source: str, label: str) -> str:
            return f"handle:{input.text}:{source}:{label}"

    provider = Provider()

    assert capture_text(provider, "source", "label", "hello") == (
        "handle:hello:source:label"
    )
