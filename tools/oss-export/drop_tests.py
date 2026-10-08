import re, sys, pathlib
# usage: drop_tests.py file test_name [test_name...]  -- removes top-level test functions (and decorators)
p = pathlib.Path(sys.argv[1]); s = p.read_text()
for name in sys.argv[2:]:
    m = re.search(rf'^((?:@[^\n]*\n)*)(async )?def {name}\(', s, re.M)
    assert m, name
    start = m.start()
    nxt = re.search(r'^(?=@|def |async def |class |[A-Za-z_#])', s[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(s)
    s = s[:start] + s[end:]
p.write_text(s)
