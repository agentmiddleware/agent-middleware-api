import ast
import pathlib
import sys

# usage: drop_tests.py file test_name [test_name...]  -- removes top-level test functions (and decorators)
p = pathlib.Path(sys.argv[1])
lines = p.read_text().splitlines(keepends=True)
functions = [
    node
    for node in ast.parse("".join(lines)).body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
]
ranges = []
for name in sys.argv[2:]:
    node = next((node for node in functions if node.name == name), None)
    assert node is not None, name
    start = min(
        (decorator.lineno for decorator in node.decorator_list), default=node.lineno
    )
    ranges.append((start - 1, node.end_lineno))

for start, end in sorted(ranges, reverse=True):
    del lines[start:end]
p.write_text("".join(lines))
