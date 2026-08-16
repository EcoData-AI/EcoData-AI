"""Calculator — a SAFE-risk tool. Arithmetic only, no I/O, never `eval()`.

The expression is parsed with `ast.parse` and the resulting tree is walked
against an explicit whitelist of node types and function names. Nothing
outside that whitelist can execute: no attribute access, no subscripting, no
imports, no name lookup beyond the two constants below, no call to anything
but the fixed math-function list. This is what makes the tool genuinely SAFE
rather than merely SAFE-by-convention — see `docs/ARCHITECTURE.md` for the
full reasoning.
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from gaia.tools.base import RiskLevel, Tool, ToolResult

MAX_EXPRESSION_LENGTH = 500
MAX_EXPONENT = 1000
MAX_FACTORIAL_ARGUMENT = 10_000

_BIN_OPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_FUNCTIONS: dict[str, Any] = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "abs": abs,
    "round": round,
    "floor": math.floor,
    "ceil": math.ceil,
    "factorial": math.factorial,
}
_CONSTANTS = {"pi": math.pi, "e": math.e}


class ExpressionError(ValueError):
    """An expression that fails the whitelist, or is malformed."""


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExpressionError("only numeric literals are allowed")
        return node.value

    if isinstance(node, ast.BinOp):
        op_fn = _BIN_OPS.get(type(node.op))
        if op_fn is None:
            raise ExpressionError(f"unsupported operator: {type(node.op).__name__}")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ExpressionError(f"exponent too large (limit {MAX_EXPONENT})")
        return op_fn(left, right)

    if isinstance(node, ast.UnaryOp):
        op_fn = _UNARY_OPS.get(type(node.op))
        if op_fn is None:
            raise ExpressionError(f"unsupported operator: {type(node.op).__name__}")
        return op_fn(_eval_node(node.operand))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise ExpressionError("only a fixed set of math functions is allowed")
        if node.keywords:
            raise ExpressionError("keyword arguments are not allowed")
        name = node.func.id
        args = [_eval_node(arg) for arg in node.args]
        if name == "factorial" and args and args[0] > MAX_FACTORIAL_ARGUMENT:
            raise ExpressionError(f"factorial argument too large (limit {MAX_FACTORIAL_ARGUMENT})")
        try:
            return _FUNCTIONS[name](*args)
        except TypeError as exc:
            raise ExpressionError(str(exc)) from exc

    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise ExpressionError(f"unknown name '{node.id}'")

    # Everything else — Attribute, Subscript, Lambda, comprehensions, Import,
    # string/collection literals, boolean/compare ops, walrus, f-strings — is
    # deliberately not handled, so it falls through to here and is rejected.
    raise ExpressionError(f"unsupported syntax: {type(node).__name__}")


def evaluate(expression: str) -> float:
    if not expression or not expression.strip():
        raise ExpressionError("empty expression")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError(f"expression too long (limit {MAX_EXPRESSION_LENGTH} characters)")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"could not parse expression: {exc.msg}") from exc
    return _eval_node(tree)


def _format_number(value: float) -> str:
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


class CalculatorTool(Tool):
    name = "calculator"
    description = (
        "Evaluate a numeric arithmetic expression. Supports + - * / // % **, "
        "parentheses, and the functions sqrt, sin, cos, tan, log, log10, exp, "
        "abs, round, floor, ceil, factorial, plus the constants pi and e. Not "
        "a general code interpreter: no variables, no other functions, no "
        "string or collection literals."
    )
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The expression to evaluate, e.g. '2 * (3 + 4)' or 'sqrt(2)'.",
            }
        },
        "required": ["expression"],
    }
    risk_level = RiskLevel.SAFE

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        expression = arguments.get("expression")
        if not isinstance(expression, str):
            return ToolResult(ok=False, content="", error="'expression' must be a string")

        try:
            result = evaluate(expression)
        except ExpressionError as exc:
            return ToolResult(ok=False, content="", error=str(exc))
        except ZeroDivisionError:
            return ToolResult(ok=False, content="", error="division by zero")
        except OverflowError:
            return ToolResult(ok=False, content="", error="result is too large to represent")
        except ValueError as exc:  # e.g. sqrt(-1), log(0)
            return ToolResult(ok=False, content="", error=str(exc))
        except Exception as exc:  # backstop — this must never raise past here
            return ToolResult(ok=False, content="", error=f"unexpected error: {exc}")

        text = _format_number(result)
        return ToolResult(ok=True, content=text, display={"expression": expression, "result": text})
