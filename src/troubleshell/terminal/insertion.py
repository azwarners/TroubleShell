"""Command insertion helpers. Insertion deliberately never adds a newline."""


def insertable_text(command: str) -> str:
    return command.replace("\r\n", "\n").replace("\r", "\n")
