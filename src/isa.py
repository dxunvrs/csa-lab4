"""Система команд и бинарное представление программы."""

from enum import IntEnum


class Opcode(IntEnum):
    ADD = 0x01
    SUB = 0x02
    MUL = 0x03
    DIV = 0x04
    MOD = 0x05
    AND = 0x06
    OR = 0x07
    XOR = 0x08
    SLT = 0x09

    ADDI = 0x10
    LW = 0x11
    SW = 0x12
    BEQ = 0x15
    BNE = 0x16
    BLT = 0x17
    BGE = 0x18
    IN = 0x19
    OUT = 0x1A

    JMP = 0x20
    CALL = 0x21
    RET = 0x22
    IRET = 0x23
    HALT = 0x24
    EI = 0x25
    DI = 0x26


R_OPCODES = {
    Opcode.ADD,
    Opcode.SUB,
    Opcode.MUL,
    Opcode.DIV,
    Opcode.MOD,
    Opcode.AND,
    Opcode.OR,
    Opcode.XOR,
    Opcode.SLT,
}

BRANCH_OPCODES = {
    Opcode.BEQ,
    Opcode.BNE,
    Opcode.BLT,
    Opcode.BGE,
}

I_OPCODES = {
    Opcode.ADDI,
    Opcode.LW,
    Opcode.SW,
    Opcode.IN,
    Opcode.OUT,
    *BRANCH_OPCODES,
}

J_OPCODES = {
    Opcode.JMP,
    Opcode.CALL,
    Opcode.RET,
    Opcode.IRET,
    Opcode.HALT,
    Opcode.EI,
    Opcode.DI,
}

DATA_MEMORY_SIZE = 4096
IMM_BITS = 18
IMM_SIGN_BIT = 1 << (IMM_BITS - 1)
IMM_MASK = (1 << IMM_BITS) - 1
MAX_PORT_NUMBER = IMM_SIGN_BIT - 1


def encode_r(opcode: Opcode, rd: int, rs1: int, rs2: int) -> int:
    """Кодирует инструкцию R-формата в 32-битное слово."""
    assert opcode in R_OPCODES
    assert 0 <= rd < 16
    assert 0 <= rs1 < 16
    assert 0 <= rs2 < 16

    return (opcode << 26) | (rd << 22) | (rs1 << 18) | (rs2 << 14)


def encode_i(opcode: Opcode, rd: int, rs1: int, imm: int) -> int:
    """Кодирует инструкцию I-формата со знаковым 18-битным операндом."""
    assert opcode in I_OPCODES
    assert 0 <= rd < 16
    assert 0 <= rs1 < 16
    assert -IMM_SIGN_BIT <= imm < IMM_SIGN_BIT
    if opcode in BRANCH_OPCODES:
        assert imm % 4 == 0

    return (opcode << 26) | (rd << 22) | (rs1 << IMM_BITS) | (imm & IMM_MASK)


def encode_j(opcode: Opcode, address: int = 0) -> int:
    """Кодирует инструкцию J-формата с абсолютным байтовым адресом."""
    assert opcode in J_OPCODES
    assert 0 <= address < (1 << 26)
    assert address % 4 == 0
    assert opcode in {Opcode.JMP, Opcode.CALL} or address == 0

    return (opcode << 26) | address


def decode(word: int) -> dict[str, int]:
    """Извлекает поля инструкции из 32-битного слова."""
    assert 0 <= word < (1 << 32)

    imm = word & IMM_MASK
    if imm & IMM_SIGN_BIT:
        imm -= 1 << IMM_BITS

    return {
        "opcode": Opcode(word >> 26),
        "rd": (word >> 22) & 0xF,
        "rs1": (word >> 18) & 0xF,
        "rs2": (word >> 14) & 0xF,
        "imm": imm,
        "address": word & 0x3FFFFFF,
    }


def to_bytes(words: list[int]) -> bytes:
    """Преобразует 32-битные слова в байты little-endian."""
    return b"".join(word.to_bytes(4, byteorder="little") for word in words)


def from_bytes(data: bytes) -> list[int]:
    """Читает 32-битные слова из байтов little-endian."""
    assert len(data) % 4 == 0

    return [
        int.from_bytes(data[offset : offset + 4], byteorder="little")
        for offset in range(0, len(data), 4)
    ]


def write_code(path: str, code: list[int], vector_count: int) -> None:
    """Записывает число векторов и машинные инструкции в бинарный файл."""
    assert 1 <= vector_count <= len(code)

    with open(path, "wb") as file:
        file.write(to_bytes([vector_count]))
        file.write(to_bytes(code))


def read_code(path: str) -> tuple[list[int], int]:
    """Читает машинные инструкции и число записей таблицы векторов."""
    with open(path, "rb") as file:
        words = from_bytes(file.read())

    assert words
    vector_count = words[0]
    code = words[1:]
    assert 1 <= vector_count <= len(code)

    return code, vector_count


def write_data(path: str, data: list[int]) -> None:
    """Записывает начальные слова памяти данных без заголовка."""
    assert len(data) * 4 < DATA_MEMORY_SIZE

    words = [value & 0xFFFFFFFF for value in data]
    with open(path, "wb") as file:
        file.write(to_bytes(words))


def read_data(path: str) -> list[int]:
    """Читает начальные слова памяти данных без заголовка."""
    with open(path, "rb") as file:
        data = file.read()

    assert len(data) < DATA_MEMORY_SIZE
    return from_bytes(data)


def to_mnemonic(word: int) -> str:
    """Возвращает текстовое представление инструкции."""
    instruction = decode(word)
    opcode = Opcode(instruction["opcode"])
    name = opcode.name

    rd = instruction["rd"]
    rs1 = instruction["rs1"]
    rs2 = instruction["rs2"]
    imm = instruction["imm"]

    if opcode in R_OPCODES:
        return f"{name} r{rd}, r{rs1}, r{rs2}"

    if opcode in BRANCH_OPCODES:
        return f"{name} r{rs1}, r{rd}, {imm}"

    if opcode in {Opcode.IN, Opcode.OUT}:
        return f"{name} r{rd}, {imm}"

    if opcode in I_OPCODES:
        return f"{name} r{rd}, r{rs1}, {imm}"

    if opcode in {Opcode.JMP, Opcode.CALL}:
        return f"{name} {instruction['address']}"

    return name


def write_listing(path: str, code: list[int]) -> None:
    """Записывает адреса, машинные слова и мнемоники инструкций."""
    with open(path, "w", encoding="utf-8") as file:
        file.writelines(
            f"{index * 4} - {word:08X} - {to_mnemonic(word)}\n"
            for index, word in enumerate(code)
        )
