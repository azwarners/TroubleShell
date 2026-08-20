from pathlib import Path

from troubleshell.config import DEFAULT_SYSTEM_PROMPT


ROOT = Path(__file__).parents[1]


def test_current_product_claims_describe_capture_and_compaction() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")
    combined = readme + "\n" + architecture + "\n" + DEFAULT_SYSTEM_PROMPT
    for stale in (
        "bounded snapshot",
        "context_line_limit",
        "context_character_limit",
        "Include recent terminal context",
    ):
        assert stale.lower() not in combined.lower()
    assert "PTY proxy" in readme
    assert "PTY proxy" in architecture
    assert "compaction" in readme.lower()
    assert "compaction" in architecture.lower()
