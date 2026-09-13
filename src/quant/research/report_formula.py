"""Translate explicit report assignments and rolling mean/std notation to DSL."""
import ast
import copy
import re


def formula_expression(formula: str, definition: str) -> str:
    """Only expand aliases declared in inline code in the same source definition."""
    def expression(text: str) -> tuple[str | None, ast.expr]:
        parsed = ast.parse(text.strip(), mode='exec')
        if len(parsed.body) != 1:
            raise ValueError('Require one explicit expression or assignment')
        row = parsed.body[0]
        if isinstance(row, ast.Expr):
            return None, row.value
        if isinstance(row, ast.Assign) and len(row.targets) == 1 and isinstance(row.targets[0], ast.Name):
            return row.targets[0].id, row.value
        raise ValueError('Unsupported report formula statement')

    aliases: dict[str, ast.expr] = {}
    for fragment in re.findall(r'`([^`\n]+)`', definition):
        try:
            name, value = expression(fragment)
        except (SyntaxError, ValueError):
            continue
        if name is not None:
            if name in aliases and ast.dump(aliases[name]) != ast.dump(value):
                raise ValueError('Conflicting report alias definitions')
            aliases[name] = value
    quoted = re.findall(r'`([^`\n]+)`', formula)
    _, root = expression(quoted[0] if quoted else formula)

    class Translate(ast.NodeTransformer):
        def __init__(self) -> None:
            self.active: set[str] = set()

        def visit_Name(self, node: ast.Name) -> ast.expr:
            if node.id not in aliases:
                return node
            if node.id in self.active:
                raise ValueError('Cyclic report alias')
            self.active.add(node.id)
            result = self.visit(copy.deepcopy(aliases[node.id]))
            self.active.remove(node.id)
            return result

        def visit_Call(self, node: ast.Call) -> ast.Call:
            if not isinstance(node.func, ast.Name):
                raise ValueError('Report formula calls must be named DSL operators')
            name = node.func.id
            if name in ('std', 'mean'):
                if len(node.args) != 2:
                    raise ValueError('Rolling report operator requires field and explicit window')
                if name == 'std':
                    if (len(node.keywords) != 1 or node.keywords[0].arg != 'ddof'
                            or not isinstance(node.keywords[0].value, ast.Constant)
                            or type(node.keywords[0].value.value) is not int
                            or node.keywords[0].value.value not in (0, 1)):
                        raise ValueError('Report std requires explicit ddof zero or one')
                    name = 'ts_std0' if node.keywords[0].value.value == 0 else 'ts_std'
                elif node.keywords:
                    raise ValueError('Unexpected mean arguments')
                else:
                    name = 'ts_mean'
                node.func = ast.Name(id=name, ctx=ast.Load())
                node.keywords = []
            node.args = [self.visit(argument) for argument in node.args]
            return node

    return ast.unparse(ast.fix_missing_locations(Translate().visit(root)))
