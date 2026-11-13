"""Трансляция AST в машинные инструкции и начальные данные."""

import argparse
import json
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from pathlib import Path

from isa import (
    DATA_MEMORY_SIZE,
    IMM_SIGN_BIT,
    Opcode,
    encode_i,
    encode_j,
    encode_r,
    write_code,
    write_data,
    write_listing,
)
from parser import Node, NodeKind, parse

WORD_BYTES = 4
WORD_SIGN_BIT = 1 << 31


class Register(IntEnum):
    ZERO = 0
    RESULT = 1
    TEMP = 5
    SP = 13
    FP = 14
    RA = 15


class Storage(StrEnum):
    MEMORY = "memory"
    STACK = "stack"
    REGISTER = "register"


class Context(StrEnum):
    MAIN = "main"
    FUNCTION = "function"
    HANDLER = "handler"

BINARY_OPCODES = {
    "+": Opcode.ADD,
    "-": Opcode.SUB,
    "*": Opcode.MUL,
    "/": Opcode.DIV,
    "%": Opcode.MOD
}

BRANCH_OPCODES = {
    "==": Opcode.BEQ,
    "!=": Opcode.BNE,
    "<": Opcode.BLT,
    ">=": Opcode.BGE
}

LITERAL_KINDS = {
    NodeKind.INTEGER,
    NodeKind.CHAR,
    NodeKind.STRING,
    NodeKind.ARRAY
}

@dataclass
class Variable:
    """Место хранения переменной: memory, stack или register."""

    storage: Storage
    location: int

@dataclass
class Frame:
    """Данные текущей функции, обработчика или основного кода."""

    context: Context
    scopes: list[dict[str, Variable]] = field(default_factory=lambda: [{}])
    local_offsets: dict[int, int] = field(default_factory=dict)
    local_size: int = 0
    saved_registers: list[int] = field(default_factory=list)
    returns: list[int] = field(default_factory=list)

class Translator:
    def __init__(self, source: str) -> None:
        self.lines = source.split("\n")
        self.program = parse(source)

        self.code: list[int] = []
        self.data: list[int] = []
        self.debug: dict[int, dict[str, int | str]] = {}

        self.globals: dict[str, Variable] = {}
        self.functions: dict[str, Node] = {}
        self.handlers: dict[int, Node] = {}

        self.function_addresses: dict[str, int] = {}
        self.calls: list[tuple[int, str]] = []
        self.static_values: dict[int, int] = {}

        self.frame = Frame(Context.MAIN)
        self.visible_globals: set[str] = set()
        self.max_frame_size = 0

    def emit(self, word: int, node: Node | None = None) -> int:
        """Добавляет инструкцию и возвращает ее индекс в code."""
        index = len(self.code)
        self.code.append(word)

        if node is None:
            self.debug[index * WORD_BYTES] = {
                "line": 0,
                "text": "<generated>"
            }
        else:
            self.debug[index * WORD_BYTES] = {
                "line": node.line,
                "text": self.lines[node.line - 1]
            }

        return index

    def push(self, register: int, node: Node | None = None) -> None:
        self.emit(encode_i(Opcode.ADDI, Register.SP, Register.SP, -WORD_BYTES), node)
        self.emit(encode_i(Opcode.SW, register, Register.SP, 0), node)

    def pop(self, register: int, node: Node | None = None) -> None:
        self.emit(encode_i(Opcode.LW, register, Register.SP, 0), node)
        self.emit(encode_i(Opcode.ADDI, Register.SP, Register.SP, WORD_BYTES), node)

    def patch_jump(self, index: int, address: int) -> None:
        self.code[index] = encode_j(Opcode.JMP, address)

    def patch_branch(
        self,
        index: int,
        opcode: Opcode,
        rs1: int,
        rd: int,
        address: int
    ) -> None:
        offset = address - index * WORD_BYTES
        self.code[index] = encode_i(opcode, rd, rs1, offset)

    def address(self) -> int:
        return len(self.code) * WORD_BYTES

    def append_data(self, values: list[int]) -> int:
        """Добавляет слова в секцию данных и возвращает байтовый адрес."""
        address = len(self.data) * WORD_BYTES
        if address + len(values) * WORD_BYTES >= DATA_MEMORY_SIZE:
            raise ValueError("Static data does not leave room for the stack")

        self.data.extend(values)
        return address

    def integer_value(self, node: Node) -> int:
        """Проверяет диапазон числового или символьного литерала."""
        if node.kind == NodeKind.CHAR:
            return ord(node.value)

        if node.kind == NodeKind.INTEGER:
            value = int(node.value)
        elif node.kind == NodeKind.UNARY and node.value == "-" and node.children[0].kind == NodeKind.INTEGER:
            value = -int(node.children[0].value)
        else:
            raise ValueError(f"Line {node.line}: expected integer literal")

        if not -WORD_SIGN_BIT <= value < WORD_SIGN_BIT:
            raise ValueError(f"Line {node.line}: integer literal out of range")

        return value

    def static_value(self, node: Node) -> int:
        """Возвращает литерал или адрес статического объекта."""
        key = id(node)
        if key in self.static_values:
            return self.static_values[key]

        if node.kind == NodeKind.STRING:
            value = self.append_data([ord(char) for char in node.value] + [0])
        elif node.kind == NodeKind.ARRAY:
            size = int(node.value)
            if size <= 0 or size * WORD_BYTES >= DATA_MEMORY_SIZE:
                raise ValueError(f"Line {node.line}: invalid array size")
            value = self.append_data([0] * size)
        else:
            value = self.integer_value(node)

        self.static_values[key] = value
        return value

    def load_constant(self, value: int, node: Node) -> None:
        if -IMM_SIGN_BIT <= value < IMM_SIGN_BIT:
            self.emit(encode_i(Opcode.ADDI, Register.RESULT, Register.ZERO, value), node)
        else:
            address = self.append_data([value])
            self.emit(encode_i(Opcode.LW, Register.RESULT, Register.ZERO, address), node)

    def collect_declarations(self) -> int:
        """Собирает функции и обработчики, затем размещает глобальные данные."""
        global_names: set[str] = set()

        for node in self.program.children:
            if node.kind == NodeKind.FUNCTION:
                if node.value in self.functions or node.value in global_names:
                    raise ValueError(f"Line {node.line}: duplicate name {node.value!r}")
                self.functions[node.value] = node

            elif node.kind == NodeKind.GLOBAL_VARIABLE:
                if node.value in global_names or node.value in self.functions:
                    raise ValueError(f"Line {node.line}: duplicate name {node.value!r}")
                global_names.add(node.value)

            elif node.kind == NodeKind.HANDLER:
                number = int(node.value)
                if number in self.handlers:
                    raise ValueError(f"Line {node.line}: duplicate handler {number}")
                self.handlers[number] = node

        for node in self.program.children:
            if node.kind == NodeKind.GLOBAL_VARIABLE:
                value = self.static_value(node.children[0])
                address = self.append_data([value])
                self.globals[node.value] = Variable(Storage.MEMORY, address)

        return max(self.handlers, default=0) + 1

    def declare(self, name: str, variable: Variable, node: Node) -> None:
        scope = self.frame.scopes[-1]
        if name in scope or name in self.functions:
            raise ValueError(f"Line {node.line}: duplicate or reserved name {name!r}")
        scope[name] = variable

    def resolve(self, name: str, node: Node) -> Variable:
        for scope in reversed(self.frame.scopes):
            if name in scope:
                return scope[name]

        if name in self.globals and (self.frame.context != Context.MAIN or name in self.visible_globals):
            return self.globals[name]

        raise ValueError(f"Line {node.line}: unknown variable {name!r}")

    def load_variable(self, variable: Variable, node: Node) -> None:
        if variable.storage == Storage.REGISTER:
            self.emit(encode_i(Opcode.ADDI, Register.RESULT, variable.location, 0), node)
        else:
            base = Register.ZERO if variable.storage == Storage.MEMORY else Register.FP
            self.emit(encode_i(Opcode.LW, Register.RESULT, base, variable.location), node)

    def store_variable(self, variable: Variable, node: Node) -> None:
        if variable.storage == Storage.REGISTER:
            self.emit(encode_i(Opcode.ADDI, variable.location, Register.RESULT, 0), node)
        else:
            base = Register.ZERO if variable.storage == Storage.MEMORY else Register.FP
            self.emit(encode_i(Opcode.SW, Register.RESULT, base, variable.location), node)

    def allocate_locals(self, node: Node) -> None:
        """Назначает отдельное смещение каждому локальному объявлению."""
        if node.kind == NodeKind.VARIABLE:
            self.frame.local_size += WORD_BYTES
            self.frame.local_offsets[id(node)] = -self.frame.local_size

        for child in node.children:
            self.allocate_locals(child)

    def reserve_locals(self) -> None:
        if self.frame.local_size:
            self.emit(encode_i(Opcode.ADDI, Register.SP, Register.SP, -self.frame.local_size))

    def record_frame_size(self, prefix_size: int) -> None:
        size = prefix_size + self.frame.local_size + len(self.frame.saved_registers) * WORD_BYTES
        self.max_frame_size = max(self.max_frame_size, size)

    def generate_index_address(self, node: Node) -> None:
        """Вычисляет адрес элемента в r1, сохраняя порядок вычислений."""
        base, index = node.children
        self.generate_expression(base)
        self.push(Register.RESULT, node)
        self.generate_expression(index)
        self.emit(encode_i(Opcode.ADDI, Register.TEMP, Register.ZERO, WORD_BYTES), node)
        self.emit(encode_r(Opcode.MUL, Register.RESULT, Register.RESULT, Register.TEMP), node)
        self.pop(Register.TEMP, node)
        self.emit(encode_r(Opcode.ADD, Register.RESULT, Register.TEMP, Register.RESULT), node)

    def generate_call(self, node: Node) -> None:
        if node.value not in self.functions:
            raise ValueError(f"Line {node.line}: unknown function {node.value!r}")

        parameters = self.functions[node.value].children[0].children
        count = len(node.children)
        if count != len(parameters):
            raise ValueError(f"Line {node.line}: wrong number of arguments")

        for argument in node.children:
            self.generate_expression(argument)
            self.push(Register.RESULT, argument)

        if count <= 4:
            for index in range(count):
                offset = (count - index - 1) * WORD_BYTES
                self.emit(encode_i(Opcode.LW, index + 1, Register.SP, offset), node)
            if count:
                self.emit(encode_i(Opcode.ADDI, Register.SP, Register.SP, count * WORD_BYTES), node)

        index = self.emit(encode_j(Opcode.CALL), node)
        self.calls.append((index, node.value))

        if count > 4:
            self.emit(encode_i(Opcode.ADDI, Register.SP, Register.SP, count * WORD_BYTES), node)

    def generate_logic(self, node: Node) -> None:
        left, right = node.children
        self.generate_expression(left)

        branch_opcode = Opcode.BEQ if node.value == "&&" else Opcode.BNE
        shortcut = self.emit(encode_i(branch_opcode, Register.ZERO, Register.RESULT, 0), node)

        self.generate_expression(right)
        self.emit(encode_r(Opcode.SLT, Register.TEMP, Register.RESULT, Register.ZERO), node)
        self.emit(encode_r(Opcode.SLT, Register.RESULT, Register.ZERO, Register.RESULT), node)
        self.emit(encode_r(Opcode.OR, Register.RESULT, Register.RESULT, Register.TEMP), node)
        finish = self.emit(encode_j(Opcode.JMP), node)

        self.patch_branch(shortcut, branch_opcode, Register.RESULT, Register.ZERO, self.address())
        self.emit(encode_i(Opcode.ADDI, Register.RESULT, Register.ZERO, 0 if node.value == "&&" else 1), node)
        self.patch_jump(finish, self.address())

    def generate_binary(self, node: Node) -> None:
        if node.value in {"&&", "||"}:
            self.generate_logic(node)
            return

        left, right = node.children
        self.generate_expression(left)
        self.push(Register.RESULT, left)
        self.generate_expression(right)
        self.pop(Register.TEMP, left)

        if node.value in BINARY_OPCODES:
            self.emit(encode_r(BINARY_OPCODES[node.value], Register.RESULT, Register.TEMP, Register.RESULT), node)
            return

        if node.value == ">":
            opcode, rs1, rd = Opcode.BLT, 1, 5
        elif node.value == "<=":
            opcode, rs1, rd = Opcode.BGE, 1, 5
        else:
            opcode, rs1, rd = BRANCH_OPCODES[node.value], 5, 1

        true_branch = self.emit(encode_i(opcode, rd, rs1, 0), node)
        self.emit(encode_i(Opcode.ADDI, Register.RESULT, Register.ZERO, 0), node)
        finish = self.emit(encode_j(Opcode.JMP), node)

        self.patch_branch(true_branch, opcode, rs1, rd, self.address())
        self.emit(encode_i(Opcode.ADDI, Register.RESULT, Register.ZERO, 1), node)
        self.patch_jump(finish, self.address())

    def generate_expression(self, node: Node) -> None:
        if node.kind in LITERAL_KINDS:
            self.load_constant(self.static_value(node), node)

        elif node.kind == NodeKind.NAME:
            self.load_variable(self.resolve(node.value, node), node)

        elif node.kind == NodeKind.IN:
            self.emit(encode_i(Opcode.IN, Register.RESULT, Register.ZERO, int(node.value)), node)

        elif node.kind == NodeKind.CALL:
            self.generate_call(node)

        elif node.kind == NodeKind.INDEX:
            self.generate_index_address(node)
            self.emit(encode_i(Opcode.LW, Register.RESULT, Register.RESULT, 0), node)

        elif node.kind == NodeKind.BINARY:
            self.generate_binary(node)

        elif node.kind == NodeKind.UNARY:
            operand = node.children[0]

            if node.value == "-" and operand.kind == NodeKind.INTEGER:
                self.load_constant(self.integer_value(node), node)
            else:
                self.generate_expression(operand)
                if node.value == "-":
                    self.emit(encode_r(Opcode.SUB, Register.RESULT, Register.ZERO, Register.RESULT), node)
                else:
                    self.emit(encode_r(Opcode.SLT, Register.TEMP, Register.RESULT, Register.ZERO), node)
                    self.emit(encode_r(Opcode.SLT, Register.RESULT, Register.ZERO, Register.RESULT), node)
                    self.emit(encode_r(Opcode.OR, Register.RESULT, Register.RESULT, Register.TEMP), node)
                    self.emit(encode_i(Opcode.ADDI, Register.TEMP, Register.ZERO, 1), node)
                    self.emit(encode_r(Opcode.SUB, Register.RESULT, Register.TEMP, Register.RESULT), node)

        else:
            raise ValueError(f"Line {node.line}: unsupported expression {node.kind}")

    def generate_block(self, node: Node, new_scope: bool = True) -> None:
        if new_scope:
            self.frame.scopes.append({})
        for statement in node.children:
            self.generate_statement(statement)
        if new_scope:
            self.frame.scopes.pop()

    def generate_statement(self, node: Node) -> None:
        if node.kind == NodeKind.VARIABLE:
            self.generate_expression(node.children[0])
            variable = Variable(Storage.STACK, self.frame.local_offsets[id(node)])
            self.declare(node.value, variable, node)
            self.store_variable(variable, node)
        elif node.kind == NodeKind.ASSIGNMENT:
            target, value = node.children
            if target.kind == NodeKind.NAME:
                variable = self.resolve(target.value, target)
                self.generate_expression(value)
                self.store_variable(variable, node)
            else:
                self.generate_index_address(target)
                self.push(Register.RESULT, target)
                self.generate_expression(value)
                self.pop(Register.TEMP, target)
                self.emit(encode_i(Opcode.SW, Register.RESULT, Register.TEMP, 0), node)
        elif node.kind == NodeKind.OUT:
            self.generate_expression(node.children[0])
            self.emit(encode_i(Opcode.OUT, Register.RESULT, Register.ZERO, int(node.value)), node)
        elif node.kind == NodeKind.EXPRESSION_STATEMENT:
            self.generate_expression(node.children[0])
        elif node.kind == NodeKind.IF:
            self.generate_expression(node.children[0])
            false_branch = self.emit(encode_i(Opcode.BEQ, Register.ZERO, Register.RESULT, 0), node)
            self.generate_block(node.children[1])
            if len(node.children) == 3:
                finish = self.emit(encode_j(Opcode.JMP), node)
                self.patch_branch(false_branch, Opcode.BEQ, Register.RESULT, Register.ZERO, self.address())
                alternative = node.children[2]
                if alternative.kind == NodeKind.IF:
                    self.generate_statement(alternative)
                else:
                    self.generate_block(alternative)
                self.patch_jump(finish, self.address())
            else:
                self.patch_branch(false_branch, Opcode.BEQ, Register.RESULT, Register.ZERO, self.address())
        elif node.kind == NodeKind.WHILE:
            start = self.address()
            self.generate_expression(node.children[0])
            finish = self.emit(encode_i(Opcode.BEQ, Register.ZERO, Register.RESULT, 0), node)
            self.generate_block(node.children[1])
            self.emit(encode_j(Opcode.JMP, start), node)
            self.patch_branch(finish, Opcode.BEQ, Register.RESULT, Register.ZERO, self.address())
        elif node.kind == NodeKind.RETURN:
            if node.children:
                self.generate_expression(node.children[0])
            else:
                self.emit(encode_i(Opcode.ADDI, Register.RESULT, Register.ZERO, 0), node)
            self.frame.returns.append(self.emit(encode_j(Opcode.JMP), node))
        else:
            raise ValueError(f"Line {node.line}: unsupported statement {node.kind}")

    def generate_function(self, node: Node) -> None:
        self.function_addresses[node.value] = self.address()
        self.frame = Frame(Context.FUNCTION)
        parameters, body = node.children[0].children, node.children[1]
        self.allocate_locals(body)
        if len(parameters) <= 4:
            self.frame.saved_registers = list(range(9, 9 + len(parameters)))
        self.record_frame_size(2 * WORD_BYTES)
        self.push(Register.RA)
        self.push(Register.FP)
        self.emit(encode_i(Opcode.ADDI, Register.FP, Register.SP, 0))
        self.reserve_locals()
        for register in self.frame.saved_registers:
            self.push(register)
        for index, parameter in enumerate(parameters):
            if len(parameters) <= 4:
                variable = Variable(Storage.REGISTER, 9 + index)
                self.emit(encode_i(Opcode.ADDI, 9 + index, index + 1, 0))
            else:
                variable = Variable(Storage.STACK, (len(parameters) - index + 1) * WORD_BYTES)
            self.declare(parameter.value, variable, parameter)
        self.generate_block(body, new_scope=False)
        self.emit(encode_i(Opcode.ADDI, Register.RESULT, Register.ZERO, 0))
        epilogue = self.address()
        for index in self.frame.returns:
            self.patch_jump(index, epilogue)
        for register in reversed(self.frame.saved_registers):
            self.pop(register)
        self.emit(encode_i(Opcode.ADDI, Register.SP, Register.FP, 0))
        self.pop(Register.FP)
        self.pop(Register.RA)
        self.emit(encode_j(Opcode.RET))

    def generate_handler(self, number: int, node: Node) -> None:
        self.code[number] = encode_j(Opcode.JMP, self.address())
        self.frame = Frame(Context.HANDLER)
        body = node.children[0]
        self.allocate_locals(body)
        registers = list(range(1, 13)) + [14, 15]
        self.record_frame_size(len(registers) * WORD_BYTES)
        for register in registers:
            self.push(register)
        self.emit(encode_i(Opcode.ADDI, Register.FP, Register.SP, 0))
        self.reserve_locals()
        self.generate_block(body, new_scope=False)
        self.emit(encode_i(Opcode.ADDI, Register.SP, Register.FP, 0))
        for register in reversed(registers):
            self.pop(register)
        self.emit(encode_j(Opcode.IRET))

    def translate(self) -> tuple[list[int], list[int], int, dict[int, dict[str, int | str]]]:
        """Генерирует инструкции, данные, число векторов и отладочную таблицу."""
        vector_count = self.collect_declarations()
        for _ in range(vector_count):
            self.emit(encode_j(Opcode.HALT))
        self.code[0] = encode_j(Opcode.JMP, self.address())
        self.frame = Frame(Context.MAIN)
        for node in self.program.children:
            if node.kind not in {NodeKind.FUNCTION, NodeKind.HANDLER}:
                self.allocate_locals(node)
        self.record_frame_size(0)
        self.emit(encode_i(Opcode.ADDI, Register.FP, Register.SP, 0))
        self.reserve_locals()
        self.emit(encode_j(Opcode.EI))
        for node in self.program.children:
            if node.kind == NodeKind.GLOBAL_VARIABLE:
                self.visible_globals.add(node.value)
            elif node.kind not in {NodeKind.FUNCTION, NodeKind.HANDLER}:
                self.generate_statement(node)
        self.emit(encode_j(Opcode.HALT))
        for node in self.functions.values():
            self.generate_function(node)
        for number, node in self.handlers.items():
            self.generate_handler(number, node)
        for index, name in self.calls:
            self.code[index] = encode_j(Opcode.CALL, self.function_addresses[name])
        if self.max_frame_size > DATA_MEMORY_SIZE - len(self.data) * WORD_BYTES:
            raise ValueError("Stack frame does not fit after static data")
        return self.code, self.data, vector_count, self.debug


def main() -> None:
    """Читает исходник и записывает бинарные и отладочные файлы."""
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("source", type=Path)
    cli.add_argument("program")
    cli.add_argument("data")
    args = cli.parse_args()
    translator = Translator(args.source.read_text(encoding="utf-8"))
    code, data, vector_count, debug = translator.translate()
    write_code(args.program, code, vector_count)
    write_data(args.data, data)
    write_listing(f"{args.program}.hex", code)
    Path(f"{args.program}.debug.json").write_text(
        json.dumps(debug, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
