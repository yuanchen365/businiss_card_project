import py_compile
import sys

files = ["main.py", "services/billing.py"]
ok = True
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print(f"OK: {f}")
    except Exception as e:
        ok = False
        print(f"FAIL: {f}: {e}")

sys.exit(0 if ok else 1)

