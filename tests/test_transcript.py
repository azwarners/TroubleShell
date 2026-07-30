from triagetty.terminal.transcript import bound_transcript, estimate_tokens, normalize_transcript


def test_normalize_removes_control_noise_and_normalizes_newlines() -> None:
    assert normalize_transcript("a\r\nb\x00\x1b[31mred") == "a\nb[31mred"


def test_bound_transcript_keeps_newest_lines_and_characters() -> None:
    assert bound_transcript("one\ntwo\nthree\nfour", max_lines=2, max_characters=100) == "three\nfour"
    assert bound_transcript("1234567890", max_lines=5, max_characters=5) == "67890"


def test_invalid_bounds_return_empty() -> None:
    assert bound_transcript("text", max_lines=0, max_characters=1) == ""
    assert bound_transcript("text", max_lines=1, max_characters=0) == ""


def test_estimate_tokens_is_a_display_only_rough_estimate() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("12345678") == 2
