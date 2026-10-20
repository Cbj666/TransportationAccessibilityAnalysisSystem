from pathlib import Path

for name in (".env", ".env.txt", "AK.txt"):
    path = Path(name)
    if not path.exists():
        continue
    print("FILE:", name, "size:", path.stat().st_size)
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            print("  KEY:", key.strip(), "value_length:", len(value.strip()))
        else:
            print("  PLAIN_VALUE length:", len(line))
