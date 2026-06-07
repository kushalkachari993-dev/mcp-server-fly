import ast
import math
import operator


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_FUNCTIONS = {
    "abs": abs,
    "ceil": math.ceil,
    "floor": math.floor,
    "round": round,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "pow": pow,
    "min": min,
    "max": max,
}

_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
}


def _evaluate(node):
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)

    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value

    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]

    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        return _BINARY_OPERATORS[type(node.op)](left, right)

    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_evaluate(node.operand))

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = _FUNCTIONS.get(node.func.id)
        if function is None:
            raise ValueError(f"Unsupported function: {node.func.id}")

        args = [_evaluate(arg) for arg in node.args]
        return function(*args)

    raise ValueError("Unsupported expression")


def register(mcp):

    @mcp.tool()
    def calculate(expression: str) -> str:
        """
        Safely evaluate a math expression.
        Supports +, -, *, /, //, %, **, parentheses, pi, e, tau,
        and functions like sqrt, sin, cos, tan, log, min, max, round.
        """

        expression = expression.strip()
        if not expression:
            return "Error: Expression cannot be empty"

        try:
            tree = ast.parse(expression, mode="eval")
            result = _evaluate(tree)
            return f"{expression} = {result}"
        except Exception as e:
            return f"Error: {e}"
