"""AST-checked legacy calibration expressions. No arbitrary attribute access or code execution."""
import ast
import math

FUNCTIONS = {k: getattr(math, k) for k in ("exp", "log", "sqrt", "sin", "cos", "tanh", "fabs")}
BUILTINS = {"abs": abs, "min": min, "max": max, "sum": sum, "len": len, "round": round, "float": float}


def compile_model_expression(source):
    if not isinstance(source, str) or len(source) > 2000:
        raise ValueError("表达式须为不超过2000字符的lambda")
    tree = ast.parse(source, mode="eval")
    if not isinstance(tree.body, ast.Lambda) or [a.arg for a in tree.body.args.args] != ["params", "years"]:
        raise ValueError("仅允许lambda params, years形式")
    if tree.body.args.defaults or tree.body.args.vararg or tree.body.args.kwarg or tree.body.args.kwonlyargs:
        raise ValueError("lambda不能使用默认值或可变参数")
    nodes = list(ast.walk(tree))
    if len(nodes) > 160:
        raise ValueError("表达式过于复杂")
    allowed = (ast.Expression, ast.Lambda, ast.arguments, ast.arg, ast.ListComp, ast.comprehension,
               ast.Name, ast.Load, ast.Store, ast.Constant, ast.BinOp, ast.UnaryOp, ast.Add,
               ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd, ast.Call, ast.Attribute,
               ast.Subscript, ast.List, ast.Tuple)
    variables = {"params", "years", "math", *BUILTINS}
    for node in nodes:
        if isinstance(node, ast.comprehension):
            if node.is_async or node.ifs or not isinstance(node.target, ast.Name) or not isinstance(node.iter, ast.Name) or node.iter.id != "years":
                raise ValueError("只允许遍历years的一层列表推导")
            variables.add(node.target.id)
    if sum(isinstance(n, ast.comprehension) for n in nodes) > 1:
        raise ValueError("不能嵌套循环")
    for node in nodes:
        if not isinstance(node, allowed):
            raise ValueError(f"不允许的语法：{type(node).__name__}")
        if isinstance(node, ast.Name) and (node.id not in variables or node.id.startswith("_")):
            raise ValueError("未允许的变量")
        if isinstance(node, ast.Attribute) and not (isinstance(node.value, ast.Name) and node.value.id == "math" and node.attr in FUNCTIONS):
            raise ValueError("仅允许已列明的math函数，禁止对象属性访问")
        if isinstance(node, ast.Call) and not ((isinstance(node.func, ast.Name) and node.func.id in BUILTINS) or isinstance(node.func, ast.Attribute)):
            raise ValueError("未允许的函数调用")
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and (not math.isfinite(node.value) or abs(node.value) > 1e15):
            raise ValueError("数值常量过大或非有限")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow) and isinstance(node.right, ast.Constant) and abs(node.right.value) > 1000:
            raise ValueError("指数过大")
    # Evaluation is only of the validated AST in an empty builtin namespace.
    return eval(compile(tree, "<validated-calibration>", "eval"), {"__builtins__": {}, "math": math, **BUILTINS})
