from triagetty.chat.models import CodeSegment, TextSegment
from triagetty.chat.parser import parse_response


def test_only_recognized_shell_fences_are_insertable() -> None:
    result = parse_response("Intro\n\n```bash\necho hi\n```\n\n```python\nprint(1)\n```")
    assert result == (
        TextSegment("Intro\n\n"),
        CodeSegment("bash", "echo hi", True),
        TextSegment("\n"),
        CodeSegment("python", "print(1)", False),
    )


def test_inline_and_untagged_code_are_not_insertable() -> None:
    result = parse_response("Use `echo hi`.\n```\necho no\n```")
    assert result[0] == TextSegment("Use `echo hi`.\n")
    assert result[1] == CodeSegment(None, "echo no", False)


def test_fenced_shell_code_preserves_multiline_content() -> None:
    result = parse_response("```sh\nif true; then\n  echo yes\nfi\n```")
    assert result[0].code == "if true; then\n  echo yes\nfi"
