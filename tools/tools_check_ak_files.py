from pathlib import Path
import hashlib

for name in (".env", ".env.txt", "AK.txt"):
    path = Path(name)
    if not path.exists():
        continue
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        value = line.split("=", 1)[1].strip() if "=" in line else line
        print(name, "length:", len(value), "sha256_8:", hashlib.sha256(value.encode()).hexdigest()[:8])
        break
