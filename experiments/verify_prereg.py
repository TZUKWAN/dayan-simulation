"""校验预注册文件完整性：重算 SHA-256 与文件尾记录值比对。
用法：python experiments/verify_prereg.py"""
import hashlib
import re
import sys
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "docs" / "preregistration_v0.1.md"
raw = p.read_text(encoding="utf-8")
m = re.search(r"sha256:([0-9a-f]{64})", raw)
if not m:
    print("文件尾无 sha256 记录——请先运行 freeze 步骤")
    sys.exit(1)
recorded = m.group(1)
body = raw[: m.start()]
actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
print(f"recorded: {recorded}")
print(f"actual:   {actual}")
print("PASS：预注册未被改动" if recorded == actual else "FAIL：预注册已被改动！")
sys.exit(0 if recorded == actual else 1)
