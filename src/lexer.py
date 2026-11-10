"""Лексический разбор исходного кода."""

from typing import NamedTuple


class Token(NamedTuple):
    kind: str
    text: str
    line: int

KEYWORDS = {
    "var",
    "fun",
    "handler",
    "if",
    "else",
    "while",
    "return",
    "arr",
    "in",
    "out"
}

DOUBLE_OPERATORS = {
    "==",
    "!=",
    "<=",
    ">=",
    "&&",
    "||"
}

SINGLE_OPERATORS = set("+-*/%!=<>(){}[],;")

ESCAPES = {
    "n": "\n",
    "t": "\t",
    "0": "\0",
    "\\": "\\",
    '"': '"',
    "'": "'"
}

def is_letter(char: str) -> bool:
    """Проверяет, является ли символ латинской буквой."""
    return "a" <= char <= "z" or "A" <= char <= "Z"


def is_digit(char: str) -> bool:
    """Проверяет, является ли символ десятичной цифрой."""
    return "0" <= char <= "9"

def read_literal(source: str, start: int) -> tuple[str, int]:
    """Читает литерал и возвращает его значение и следующую позицию."""
    quote = source[start]
    position = start + 1
    value = []

    while position < len(source):
        char = source[position]

        if char == quote:
            text = "".join(value)
            if quote == "'":
                assert len(text) == 1, "Character literal must contain one character"
            return text, position + 1

        assert char not in "\r\n", "Newline inside literal"
        assert ord(char) < 128, "Non-ASCII character inside literal"

        if char == "\\":
            position += 1
            assert position < len(source), "Unfinished escape sequence"
            char = source[position]
            assert char in ESCAPES, "Unknown escape sequence"
            value.append(ESCAPES[char])
        else:
            value.append(char)

        position += 1

    raise AssertionError("Unterminated literal")

def tokenize(source: str) -> list[Token]:
    """Разбивает исходный код на токены."""
    tokens: list[Token] = []
    position = 0
    line = 1

    while position < len(source):
        char = source[position]

        if char in " \t\r\n":
            if char == "\n":
                line += 1
            position += 1
            continue

        if source.startswith("//", position):
            while position < len(source) and source[position] != "\n":
                position += 1
            continue

        if is_digit(char):
            start = position
            while position < len(source) and is_digit(source[position]):
                position += 1
            tokens.append(Token("integer", source[start:position], line))
            continue

        if is_letter(char) or char == "_":
            start = position
            while position < len(source):
                char = source[position]
                if not (is_letter(char) or is_digit(char) or char == "_"):
                    break
                position += 1

            text = source[start:position]
            kind = text if text in KEYWORDS else "identifier"
            tokens.append(Token(kind, text, line))
            continue

        if char in "\"'":
            kind = "string" if char == '"' else "char"
            text, position = read_literal(source, position)
            tokens.append(Token(kind, text, line))
            continue

        operator = source[position:position+2]
        if operator in DOUBLE_OPERATORS:
            tokens.append(Token(operator, operator, line))
            position += 2
            continue

        if char in SINGLE_OPERATORS:
            tokens.append(Token(char, char, line))
            position += 1
            continue

        raise AssertionError(f"Unexpected character at line {line}: {char!r}")

    tokens.append(Token("eof", "", line))
    return tokens
