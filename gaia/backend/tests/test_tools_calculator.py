"""Calculator: correct arithmetic, and the AST whitelist actually blocks everything else."""

from __future__ import annotations

import math

import pytest

from gaia.tools.base import RiskLevel
from gaia.tools.calculator import CalculatorTool, ExpressionError, evaluate


def test_basic_arithmetic_and_precedence():
    assert evaluate("2 + 3 * 4") == 14
    assert evaluate("(2 + 3) * 4") == 20
    assert evaluate("2 ** 10") == 1024
    assert evaluate("7 // 2") == 3
    assert evaluate("7 % 2") == 1
    assert evaluate("-5 + 2") == -3


def test_whitelisted_functions_and_constants():
    assert evaluate("sqrt(16)") == 4
    assert evaluate("round(pi, 2)") == 3.14
    assert math.isclose(evaluate("sin(0)"), 0.0)
    assert evaluate("factorial(5)") == 120
    assert evaluate("floor(3.7)") == 3
    assert evaluate("ceil(3.2)") == 4


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo hi')",
        "().__class__",
        "().__class__.__bases__[0]",
        "open('/etc/passwd')",
        "[x for x in range(10)]",
        "lambda: 1",
        "1 if True else 2",
        "'a string'",
        "1; 2",
        "os.system('echo hi')",
        "x + 1",  # unknown name
        "not_a_function(1)",
    ],
)
def test_rejects_unsafe_or_unsupported_syntax(expression):
    with pytest.raises(ExpressionError):
        evaluate(expression)


def test_rejects_overlong_expression():
    with pytest.raises(ExpressionError):
        evaluate("1+" * 1000 + "1")


def test_rejects_huge_exponent():
    with pytest.raises(ExpressionError):
        evaluate("2 ** 100000")


def test_rejects_huge_factorial():
    with pytest.raises(ExpressionError):
        evaluate("factorial(1000000)")


def test_rejects_empty_expression():
    with pytest.raises(ExpressionError):
        evaluate("")
    with pytest.raises(ExpressionError):
        evaluate("   ")


def test_calculator_is_safe_risk():
    assert CalculatorTool.risk_level is RiskLevel.SAFE


async def test_execute_returns_ok_result():
    tool = CalculatorTool()
    result = await tool.execute({"expression": "2 * (3 + 4)"})
    assert result.ok is True
    assert result.content == "14"
    assert result.display == {"expression": "2 * (3 + 4)", "result": "14"}


async def test_execute_division_by_zero_is_reported_not_raised():
    tool = CalculatorTool()
    result = await tool.execute({"expression": "1 / 0"})
    assert result.ok is False
    assert "division by zero" in (result.error or "")


async def test_execute_domain_error_is_reported_not_raised():
    tool = CalculatorTool()
    result = await tool.execute({"expression": "sqrt(-1)"})
    assert result.ok is False
    assert result.error


async def test_execute_rejects_non_string_expression():
    tool = CalculatorTool()
    result = await tool.execute({"expression": 123})
    assert result.ok is False
    assert "must be a string" in (result.error or "")


async def test_execute_never_raises_on_malicious_input():
    tool = CalculatorTool()
    result = await tool.execute({"expression": "__import__('os').system('echo hi')"})
    assert result.ok is False
    assert result.error
