"""python3 test_dimming.py — 디밍 명령 패킷이 월패드 실측값과 같은지 확인 (2026-11-16 캡처)"""

import ast

src = open(__file__.replace("test_dimming.py", "ezville.py")).read()
ns = {}
fn = [n for n in ast.parse(src).body if getattr(n, "name", "") == "checksum"]
exec(compile(ast.Module(fn, []), "ezville.py", "exec"), ns)

for level, captured in [(1, "BA26"), (2, "8A06"), (3, "9A26"), (4, "EA86")]:
    cmd = f"F70E11410301{level}1" + "00"
    assert ns["checksum"](cmd + "0000") == cmd + captured, level
print("OK")
