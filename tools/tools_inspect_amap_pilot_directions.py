from pathlib import Path
import json
import re
from difflib import SequenceMatcher


def normalize_name(value: str) -> str:
    value = str(value or "").strip()
    value = value.replace("（", "(").replace("）", ")").replace("　", "")
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"\(.*?\)", "", value)
    value = value.replace("公交车站", "").replace("公交站", "")
    value = re.sub(r"站$", "", value)
    return value


def loop_suffix(value: str) -> str:
    value = str(value or "")
    for suffix in ("内环", "外环", "区间"):
        if suffix in value:
            return suffix
    return ""


for label in ("H89路", "910路", "402路", "鄂101路"):
    path = Path("data/interim/amap_pilot") / f"raw_{label}.json"
    if not path.exists():
        continue
    payload = json.loads(path.read_text(encoding="utf-8"))
    public = payload["public"]
    public_names = {normalize_name(s) for s in public["stations"]}
    print("=" * 90)
    print(label, "public stations:", len(public_names), "route:", public["route"])
    for line in payload["directions"]:
        names = {normalize_name(s.get("name", "")) for s in line.get("busstops", [])}
        overlap = len(public_names & names) / max(1, len(public_names | names))
        start = line.get("start_stop", "")
        end = line.get("end_stop", "")
        print(
            f"  overlap={overlap:.3f} stations={len(names):3d} suffix={loop_suffix(line.get('name','')) or '-':2s} "
            f"name={line.get('name')} | {start} -> {end}"
        )
