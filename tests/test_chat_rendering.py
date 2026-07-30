from triagetty.chat.rendering import code_to_pango, prose_to_pango


def test_prose_rendering_escapes_markup_and_supports_small_subset() -> None:
    rendered = prose_to_pango("**bold** and `code` <unsafe>")
    assert rendered == "<b>bold</b> and <tt>code</tt> &lt;unsafe&gt;"


def test_code_rendering_escapes_markup() -> None:
    assert code_to_pango("echo '<hello>'") == "<tt>echo '&lt;hello&gt;'</tt>"
