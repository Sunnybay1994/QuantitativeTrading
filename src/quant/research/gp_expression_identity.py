"""Conservative identity for verified GP symmetries; no algebraic rewriting."""
import ast

VERSION = 'ts_corr_cov_argument_order_v1'
LEGACY = 'literal_expression_v1'


def canonical_expression(expression: str, version: str = VERSION) -> str:
    if version == LEGACY:
        return expression
    if version != VERSION:
        raise ValueError(f'Unsupported GP expression identity: {version}')

    class Symmetry(ast.NodeTransformer):
        def visit_Call(self, node):
            self.generic_visit(node)
            # Corr (batch 64) and cov (batch 65) have independently verified
            # swapped-input identity. Do not rewrite +/-/*, signs or windows.
            if (isinstance(node.func, ast.Name) and node.func.id in {'ts_corr', 'ts_cov'}
                    and len(node.args) == 3 and not node.keywords):
                node.args[:2] = sorted(node.args[:2], key=ast.dump)
            return node

    return ast.unparse(Symmetry().visit(ast.parse(expression, mode='eval')).body)


def expression_key(expression: str, version: str) -> str:
    value = canonical_expression(expression, version)
    return value if version == LEGACY else ast.dump(ast.parse(value, mode='eval'))
