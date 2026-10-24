# Шулай Роман Юрьевич, P3215

- Архитектура компьютера
- Лабораторная работа №4
- Вариант: `alg | risc | harv | hw | trap | port | cstr | vector | alg3`
- Без усложнения

## Язык программирования

### Синтаксис
```
program             ::= { top_level_decl }

top_level_decl      ::= fun_decl
                      | handler_decl
                      | top_level_stmt

fun_decl            ::= "fun" identifier "(" [ param_list ] ")" block
handler_decl        ::= "handler" integer block

top_level_stmt      ::= var_decl
                      | assignment_stmt
                      | if_stmt
                      | while_stmt
                      | expr_stmt

param_list          ::= identifier { "," identifier }
block               ::= "{" { statement } "}"

statement           ::= var_decl
                      | assignment_stmt
                      | if_stmt
                      | while_stmt
                      | return_stmt
                      | expr_stmt

var_decl            ::= "var" identifier "=" expr ";"
assignment_stmt     ::= lvalue "=" expr ";"
lvalue              ::= identifier [ "[" expr "]" ]

if_stmt             ::= "if" "(" expr ")" block [ "else" ( block | if_stmt ) ]
while_stmt          ::= "while" "(" expr ")" block
return_stmt         ::= "return" [ expr ] ";"
expr_stmt           ::= expr ";"

expr                ::= logic_or_expr

logic_or_expr       ::= logic_and_expr { "||" logic_and_expr }
logic_and_expr      ::= equality_expr  { "&&" equality_expr }
equality_expr       ::= relational_expr { ( "==" | "!=" ) relational_expr }
relational_expr     ::= additive_expr   { ( "<" | "<=" | ">" | ">=" ) additive_expr }
additive_expr       ::= mult_expr       { ( "+" | "-" ) mult_expr }
mult_expr           ::= unary_expr      { ( "*" | "/" | "%" ) unary_expr }

unary_expr          ::= [ "-" | "!" ] primary_expr

primary_expr        ::= integer
                      | char_literal
                      | string_literal
                      | identifier [ "[" expr "]" ]
                      | fun_call
                      | io_expr
                      | arr_alloc
                      | "(" expr ")"

fun_call            ::= identifier "(" [ arg_list ] ")"
arg_list            ::= expr { "," expr }

arr_alloc           ::= "arr" "(" expr ")"
io_expr             ::= "in" "(" expr ")"
                      | "out" "(" expr "," expr ")"

identifier          ::= ( letter | "_" ) { letter | digit | "_" }
integer             ::= [ "-" ] digit { digit }
string_literal      ::= '"' { <any char except quote> } '"'
char_literal        ::= "'" <any char except apostrophe> "'"

letter              ::= "a" ... "z" | "A" ... "Z"
digit               ::= "0" ... "9"
```

### Ключевые слова

- `var` - объявление переменной
- `if (expr) {}`, `else {}` - условные переходы
- `while (expr) {}` - цикл
- `out(port, value)` - вывод
- `in(port)` - ввод
- `arr(N)` - выделить память под массив из N слов
- `handler N {}` - обработчик прерывания
- `fun name (arg1, arg2, ...) {}` - объявление функции
- `return` / `return expr` - возврат из функции

### Семантика

#### Стратегия вычислений

- Код выполняется последовательно
- Переменные объявляются до использования
- Передача аргументов в функции происходит по значению - передается копия значения аргумента (для чисел - само число, для массивов и строк - копия указателя)
- Выражения вычисляются слева направа с учетом приоритета операторов (`() -> -, ! -> *, /, % -> +, - -> <, <=, >, >= -> ==, != -> && -> ||)

#### Описание семантики

- Для переменных, объявленных на верхнем уровне, глобальная область видимости
- Для аргументов функций и локальных переменных локальная область видимости 
- Названия переменных начинаются с латинской буквы или нижнего подчеркивания, в названии переменных также могут содержаться цифры
- Бестиповая модель данных
- Нет констант
- Литералы: числа, строки и ASCII-символы
- Организация массивов: выделение памяти через `arr(N)`, доступ к элементу через `a[i]`
- Разделитель - `;`
- Комментарии - `//`
