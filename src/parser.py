"""Синтаксический разбор и представление AST."""

from dataclasses import dataclass, field
from enum import StrEnum

from isa import MAX_PORT_NUMBER
from lexer import Token, TokenKind, tokenize


class NodeKind(StrEnum):
    PROGRAM = "program"
    FUNCTION = "function"
    PARAMETER = "parameter"
    PARAMETERS = "parameters"
    HANDLER = "handler"
    BLOCK = "block"
    GLOBAL_VARIABLE = "global_variable"
    VARIABLE = "variable"
    ASSIGNMENT = "assignment"
    EXPRESSION_STATEMENT = "expression_statement"
    IF = "if"
    WHILE = "while"
    RETURN = "return"
    OUT = "out"
    IN = "in"
    ARRAY = "array"
    INTEGER = "integer"
    CHAR = "char"
    STRING = "string"
    UNARY = "unary"
    BINARY = "binary"
    CALL = "call"
    NAME = "name"
    INDEX = "index"


@dataclass
class Node:
    kind: NodeKind
    value: str = ""
    children: list["Node"] = field(default_factory=list)
    line: int = 0

# Отсортированы по приоритету (от меньшего к большему)
BINARY_LEVELS = (
    (TokenKind.OR,),
    (TokenKind.AND,),
    (TokenKind.EQ, TokenKind.NE),
    (TokenKind.LT, TokenKind.LE, TokenKind.GT, TokenKind.GE),
    (TokenKind.PLUS, TokenKind.MINUS),
    (TokenKind.STAR, TokenKind.SLASH, TokenKind.PERCENT)
)

class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.position = 0

    def current(self) -> Token:
        return self.tokens[self.position]

    def match(self, kind: TokenKind) -> bool:
        if self.current().kind != kind:
            return False
        self.position += 1
        return True

    def expect(self, kind: TokenKind) -> Token:
        token = self.current()
        assert token.kind == kind, f"Line {token.line}: expected {kind}, got {token.kind}"
        self.position += 1
        return token

    def parse_program(self) -> Node:
        declarations = []

        while self.current().kind != TokenKind.EOF:
            if self.current().kind == TokenKind.FUN:
                declarations.append(self.parse_function())
            elif self.current().kind == TokenKind.HANDLER:
                declarations.append(self.parse_handler())
            else:
                declarations.append(self.parse_statement("main", top_level=True))

        self.expect(TokenKind.EOF)
        return Node(NodeKind.PROGRAM, children=declarations)

    def parse_function(self) -> Node:
        token = self.expect(TokenKind.FUN)
        name = self.expect(TokenKind.IDENTIFIER).text
        self.expect(TokenKind.LPAREN)
        parameters = []

        if self.current().kind != TokenKind.RPAREN:
            while True:
                parameter = self.expect(TokenKind.IDENTIFIER)
                parameters.append(
                    Node(NodeKind.PARAMETER, parameter.text, line=parameter.line)
                )
                if not self.match(TokenKind.COMMA):
                    break

        self.expect(TokenKind.RPAREN)
        body = self.parse_block("function")

        return Node(
            NodeKind.FUNCTION,
            name,
            [Node(NodeKind.PARAMETERS, children=parameters), body],
            token.line
        )

    def parse_handler(self) -> Node:
        token = self.expect(TokenKind.HANDLER)
        number = self.expect(TokenKind.INTEGER)
        assert 1 <= int(number.text) <= MAX_PORT_NUMBER, f"Line {number.line}: invalid handler number"
        body = self.parse_block("handler")

        return Node(NodeKind.HANDLER, number.text, [body], token.line)

    def parse_block(self, context: str) -> Node:
        token = self.expect(TokenKind.LBRACE)
        statements = []

        while self.current().kind != TokenKind.RBRACE:
            assert self.current().kind != TokenKind.EOF, f"Line {self.current().line}: expected closing brace"
            statements.append(self.parse_statement(context))

        self.expect(TokenKind.RBRACE)
        return Node(NodeKind.BLOCK, children=statements, line=token.line)

    def parse_statement(self, context: str, top_level: bool = False) -> Node:
        kind = self.current().kind

        if kind == TokenKind.VAR:
            return self.parse_variable(top_level)
        if kind == TokenKind.IF:
            return self.parse_if(context)
        if kind == TokenKind.WHILE:
            return self.parse_while(context)
        if kind == TokenKind.RETURN:
            return self.parse_return(context)
        if kind == TokenKind.OUT:
            return self.parse_output()

        expression = self.parse_expresion()

        if self.match(TokenKind.ASSIGN):
            assert kind == TokenKind.IDENTIFIER and expression.kind in {NodeKind.NAME, NodeKind.INDEX}, f"Line {expression.line}: invalid assignment target"
            value = self.parse_expresion()
            self.expect(TokenKind.SEMICOLON)
            return Node(
                NodeKind.ASSIGNMENT,
                children=[expression, value],
                line=expression.line
            )

        self.expect(TokenKind.SEMICOLON)
        return Node(
            NodeKind.EXPRESSION_STATEMENT,
            children=[expression],
            line=expression.line
        )

    def parse_variable(self, global_scope: bool) -> Node:
        token = self.expect(TokenKind.VAR)
        name = self.expect(TokenKind.IDENTIFIER).text
        self.expect(TokenKind.ASSIGN)

        if self.current().kind == TokenKind.ARR:
            initializer = self.parse_array()
        elif global_scope:
            initializer = self.parse_global_initializer()
        else:
            initializer = self.parse_expresion()

        self.expect(TokenKind.SEMICOLON)
        kind = NodeKind.GLOBAL_VARIABLE if global_scope else NodeKind.VARIABLE
        return Node(kind, name, [initializer], token.line)

    def parse_global_initializer(self) -> Node:
        token = self.current()

        if token.kind == TokenKind.MINUS:
            self.expect(TokenKind.MINUS)
            number = self.expect(TokenKind.INTEGER)
            return Node(
                NodeKind.UNARY,
                "-",
                [Node(NodeKind.INTEGER, number.text, line=number.line)],
                token.line
            )

        assert token.kind in {TokenKind.INTEGER, TokenKind.CHAR, TokenKind.STRING}, f"Line {token.line}: expected static global initializer"
        self.position += 1
        return Node(NodeKind(token.kind.value), token.text, line=token.line)

    def parse_array(self) -> Node:
        token = self.expect(TokenKind.ARR)
        self.expect(TokenKind.LPAREN)
        size = self.expect(TokenKind.INTEGER)
        assert int(size.text) > 0, f"Line {size.line}: array size must be positive"
        self.expect(TokenKind.RPAREN)
        return Node(NodeKind.ARRAY, size.text, line=token.line)

    def parse_if(self, context: str) -> Node:
        token = self.expect(TokenKind.IF)
        self.expect(TokenKind.LPAREN)
        condition = self.parse_expresion()
        self.expect(TokenKind.RPAREN)
        then_block = self.parse_block(context)
        children = [condition, then_block]

        if self.match(TokenKind.ELSE):
            if self.current().kind == TokenKind.IF:
                children.append(self.parse_if(context))
            else:
                children.append(self.parse_block(context))

        return Node(NodeKind.IF, children=children, line=token.line)

    def parse_while(self, context: str) -> Node:
        token = self.expect(TokenKind.WHILE)
        self.expect(TokenKind.LPAREN)
        condition = self.parse_expresion()
        self.expect(TokenKind.RPAREN)
        body = self.parse_block(context)

        return Node(NodeKind.WHILE, children=[condition, body], line=token.line)

    def parse_return(self, context: str) -> Node:
        token = self.expect(TokenKind.RETURN)
        assert context == "function", f"Line {token.line}: return is allowed only inside function"

        children = []
        if self.current().kind != TokenKind.SEMICOLON:
            children.append(self.parse_expresion())

        self.expect(TokenKind.SEMICOLON)
        return Node(NodeKind.RETURN, children=children, line=token.line)

    def parse_port(self) -> Token:
        port = self.expect(TokenKind.INTEGER)
        assert 1 <= int(port.text) <= MAX_PORT_NUMBER, f"Line {port.line}: invalid port number"
        return port

    def parse_output(self) -> Node:
        token = self.expect(TokenKind.OUT)
        self.expect(TokenKind.LPAREN)
        port = self.parse_port()
        self.expect(TokenKind.COMMA)
        value = self.parse_expresion()
        self.expect(TokenKind.RPAREN)
        self.expect(TokenKind.SEMICOLON)

        return Node(NodeKind.OUT, port.text, [value], token.line)

    def parse_expresion(self, level: int = 0) -> Node:
        if level == len(BINARY_LEVELS):
            return self.parse_unary()

        left = self.parse_expresion(level+1)

        while self.current().kind in BINARY_LEVELS[level]:
            operator = self.current()
            self.position += 1
            right = self.parse_expresion(level+1)
            left = Node(NodeKind.BINARY, operator.text, [left, right], operator.line)

        return left

    def parse_unary(self) -> Node:
        token = self.current()

        if token.kind in {TokenKind.MINUS, TokenKind.NOT}:
            self.position += 1
            operand = self.parse_unary()
            return Node(NodeKind.UNARY, token.text, [operand], token.line)

        return self.parse_primary()

    def parse_primary(self) -> Node:
        token = self.current()

        if token.kind in {TokenKind.INTEGER, TokenKind.CHAR, TokenKind.STRING}:
            self.position += 1
            return Node(NodeKind(token.kind.value), token.text, line=token.line)

        if self.match(TokenKind.LPAREN):
            expression = self.parse_expresion()
            self.expect(TokenKind.RPAREN)
            return expression

        if self.match(TokenKind.IN):
            self.expect(TokenKind.LPAREN)
            port = self.parse_port()
            self.expect(TokenKind.RPAREN)
            return Node(NodeKind.IN, port.text, line=token.line)

        if token.kind == TokenKind.IDENTIFIER:
            self.position += 1

            if self.match(TokenKind.LPAREN):
                arguments = []

                if self.current().kind != TokenKind.RPAREN:
                    while True:
                        arguments.append(self.parse_expresion())
                        if not self.match(TokenKind.COMMA):
                            break

                self.expect(TokenKind.RPAREN)
                return Node(NodeKind.CALL, token.text, children=arguments, line=token.line)

            name = Node(NodeKind.NAME, token.text, line=token.line)

            if self.match(TokenKind.LBRACKET):
                index = self.parse_expresion()
                self.expect(TokenKind.RBRACKET)
                return Node(NodeKind.INDEX, children=[name, index], line=token.line)

            return name

        raise AssertionError(f"Line {token.line}: expected expression, got {token.kind}")

def parse(source: str) -> Node:
    """Строит AST программы из исходного текста."""
    return Parser(tokenize(source)).parse_program()

def format_ast(node: Node, depth: int = 0) -> str:
    """Возвращает читаемое дерево."""
    label = node.kind.value
    if node.value:
        label += f" {node.value!r}"

    lines = [f"{' ' * depth}{label}"]
    lines.extend(format_ast(child, depth + 1) for child in node.children)
    return "\n".join(lines)
