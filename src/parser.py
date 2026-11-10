"""Синтаксический разбор и представление AST."""

from dataclasses import dataclass, field

from isa import MAX_PORT_NUMBER
from lexer import Token, tokenize


@dataclass
class Node:
    kind: str
    value: str = ""
    children: list["Node"] = field(default_factory=list)
    line: int = 0

# Отсортированы по приоритету (от меньшего к большему)
BINARY_LEVELS = (
    ("||",),
    ("&&",),
    ("==", "!="),
    ("<", "<=", ">", ">="),
    ("+", "-"),
    ("*", "/", "%")
)

class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.position = 0

    def current(self) -> Token:
        return self.tokens[self.position]

    def match(self, kind: str) -> bool:
        if self.current().kind != kind:
            return False
        self.position += 1
        return True

    def expect(self, kind: str) -> Token:
        token = self.current()
        assert token.kind == kind, f"Line {token.line}: expected {kind}, got {token.kind}"
        self.position += 1
        return token

    def parse_program(self) -> Node:
        declarations = []

        while self.current().kind != "eof":
            if self.current().kind == "fun":
                declarations.append(self.parse_function())
            elif self.current().kind == "handler":
                declarations.append(self.parse_handler())
            else:
                declarations.append(self.parse_statement("main", top_level=True))

        self.expect("eof")
        return Node("program", children=declarations)

    def parse_function(self) -> Node:
        token = self.expect("fun")
        name = self.expect("identifier").text
        self.expect("(")
        parameters = []

        if self.current().kind != ")":
            while True:
                parameter = self.expect("identifier")
                parameters.append(
                    Node("parameter", parameter.text, line=parameter.line)
                )
                if not self.match(","):
                    break

        self.expect(")")
        body = self.parse_block("function")

        return Node(
            "function",
            name,
            [Node("parameters", children=parameters), body],
            token.line
        )

    def parse_handler(self) -> Node:
        token = self.expect("handler")
        number = self.expect("integer")
        assert 1 <= int(number.text) <= MAX_PORT_NUMBER, f"Line {number.line}: invalid handler number"
        body = self.parse_block("handler")

        return Node("handler", number.text, [body], token.line)

    def parse_block(self, context: str) -> Node:
        token = self.expect("{")
        statements = []

        while self.current().kind != "}":
            assert self.current().kind != "eof", f"Line {self.current().line}: expected closing brace"
            statements.append(self.parse_statement(context))

        self.expect("}")
        return Node("block", children=statements, line=token.line)

    def parse_statement(self, context: str, top_level: bool = False) -> Node:
        kind = self.current().kind

        if kind == "var":
            return self.parse_variable(top_level)
        if kind == "if":
            return self.parse_if(context)
        if kind == "while":
            return self.parse_while(context)
        if kind == "return":
            return self.parse_return(context)
        if kind == "out":
            return self.parse_output()

        expression = self.parse_expresion()

        if self.match("="):
            assert kind == "identifier" and expression.kind in {"name", "index"}, f"Line {expression.line}: invalid assignment target"
            value = self.parse_expresion()
            self.expect(";")
            return Node(
                "assignment",
                children=[expression, value],
                line=expression.line
            )

        self.expect(";")
        return Node(
            "expression_statement",
            children=[expression],
            line=expression.line
        )

    def parse_variable(self, global_scope: bool) -> Node:
        token = self.expect("var")
        name = self.expect("identifier").text
        self.expect("=")

        if self.current().kind == "arr":
            initializer = self.parse_array()
        elif global_scope:
            initializer = self.parse_global_initializer()
        else:
            initializer = self.parse_expresion()

        self.expect(";")
        kind = "global_variable" if global_scope else "variable"
        return Node(kind, name, [initializer], token.line)

    def parse_global_initializer(self) -> Node:
        token = self.current()

        if token.kind == "-":
            self.expect("-")
            number = self.expect("integer")
            return Node(
                "unary",
                "-",
                [Node("integer", number.text, line=number.line)],
                token.line
            )

        assert token.kind in {"integer", "char", "string"}, f"Line {token.line}: expected static global initializer"
        self.position += 1
        return Node(token.kind, token.text, line=token.line)

    def parse_array(self) -> Node:
        token = self.expect("arr")
        self.expect("(")
        size = self.expect("integer")
        assert int(size.text) > 0, f"Line {size.line}: array size must be positive"
        self.expect(")")
        return Node("array", size.text, line=token.line)

    def parse_if(self, context: str) -> Node:
        token = self.expect("if")
        self.expect("(")
        condition = self.parse_expresion()
        self.expect(")")
        then_block = self.parse_block(context)
        children = [condition, then_block]

        if self.match("else"):
            if self.current().kind == "if":
                children.append(self.parse_if(context))
            else:
                children.append(self.parse_block(context))

        return Node("if", children=children, line=token.line)

    def parse_while(self, context: str) -> Node:
        token = self.expect("while")
        self.expect("(")
        condition = self.parse_expresion()
        self.expect(")")
        body = self.parse_block(context)

        return Node("while", children=[condition, body], line=token.line)

    def parse_return(self, context: str) -> Node:
        token = self.expect("return")
        assert context == "function", f"Line {token.line}: return is allowed only inside function"

        children = []
        if self.current().kind != ";":
            children.append(self.parse_expresion())

        self.expect(";")
        return Node("return", children=children, line=token.line)

    def parse_port(self) -> Token:
        port = self.expect("integer")
        assert 1 <= int(port.text) <= MAX_PORT_NUMBER, f"Line {port.line}: invalid port number"
        return port

    def parse_output(self) -> Node:
        token = self.expect("out")
        self.expect("(")
        port = self.parse_port()
        self.expect(",")
        value = self.parse_expresion()
        self.expect(")")
        self.expect(";")

        return Node("out", port.text, [value], token.line)

    def parse_expresion(self, level: int = 0) -> Node:
        if level == len(BINARY_LEVELS):
            return self.parse_unary()

        left = self.parse_expresion(level+1)

        while self.current().kind in BINARY_LEVELS[level]:
            operator = self.current()
            self.position += 1
            right = self.parse_expresion(level+1)
            left = Node("binary", operator.text, [left, right], operator.line)

        return left

    def parse_unary(self) -> Node:
        token = self.current()

        if token.kind in {"-", "!"}:
            self.position += 1
            operand = self.parse_unary()
            return Node("unary", token.text, [operand], token.line)

        return self.parse_primary()

    def parse_primary(self) -> Node:
        token = self.current()

        if token.kind in {"integer", "char", "string"}:
            self.position += 1
            return Node(token.kind, token.text, line=token.line)

        if self.match("("):
            expression = self.parse_expresion()
            self.expect(")")
            return expression

        if self.match("in"):
            self.expect("(")
            port = self.parse_port()
            self.expect(")")
            return Node("in", port.text, line=token.line)

        if token.kind == "identifier":
            self.position += 1

            if self.match("("):
                arguments = []

                if self.current().kind != ")":
                    while True:
                        arguments.append(self.parse_expresion())
                        if not self.match(","):
                            break

                self.expect(")")
                return Node("call", token.text, children=arguments, line=token.line)

            name = Node("name", token.text, line=token.line)

            if self.match("["):
                index = self.parse_expresion()
                self.expect("]")
                return Node("index", children=[name, index], line=token.line)

            return name

        raise AssertionError(f"Line {token.line}: expected expression, got {token.kind}")

def parse(source: str) -> Node:
    """Строит AST программы из исходного текста."""
    return Parser(tokenize(source)).parse_program()

def format_ast(node: Node, depth: int = 0) -> str:
    """Возвращает читаемое дерево."""
    label = node.kind
    if node.value:
        label += f" {node.value!r}"

    lines = [f"{' ' * depth}{label}"]
    lines.extend(format_ast(child, depth + 1) for child in node.children)
    return "\n".join(lines)
