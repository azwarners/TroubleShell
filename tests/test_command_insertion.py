from triagetty.terminal.insertion import insertable_text


def test_insertion_never_adds_execution_newline() -> None:
    assert insertable_text("sudo nginx -t") == "sudo nginx -t"
    assert insertable_text("echo one\r\necho two") == "echo one\necho two"
