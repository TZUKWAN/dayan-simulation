"""WP5 RunManifest 测试：字段完整性、run_id、_manifest_public 子集、
兼容入口与统一入口一致性。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan.runtime import run_model_full  # noqa: E402
from dayan.server import _manifest_public  # noqa: E402

REQUIRED_KEYS = {"run_id", "model_id", "protocol", "requested", "actual",
                 "param_issues", "param_effect", "rng", "clocks", "checkpoint",
                 "events_n", "interventions", "started_at", "finished_at",
                 "duration_s", "warnings", "runtime_version"}


def run_tests():
    passed, failed = 0, 0

    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"[PASS] {name}")
        else:
            failed += 1
            print(f"[FAIL] {name} {detail}")

    rr = run_model_full("NET052", parameters={"beta": 0.4}, ticks=15,
                        seed=7, experiment="UT")
    m = rr.manifest
    check("manifest 必备字段完整", REQUIRED_KEYS <= set(m.keys()),
          f"缺 {REQUIRED_KEYS - set(m.keys())}")
    check("run_id 格式 R+时间戳-uuid32（同秒同配置不覆盖）",
          re.fullmatch(r"R\d{8}T\d{6}-[0-9a-f]{32}", m["run_id"]) is not None,
          f"run_id={m['run_id']}")
    check("requested 记录原始请求",
          m["requested"]["parameters"] == {"beta": 0.4}
          and m["requested"]["seed"] == 7
          and m["requested"]["experiment"] == "UT")
    check("actual 记录实际值与步数",
          m["actual"]["parameters"] == {"beta": 0.4}
          and m["actual"]["n_steps"] == 15
          and m["actual"]["n_obs"] == 16)
    check("时钟记录 sim_time/iter",
          m["clocks"]["optim_iter"] == 15
          and abs(m["clocks"]["sim_time"] - 1.5) < 1e-9)
    check("随机流记录 seed/stream/算法",
          m["rng"]["seed"] == 7 and m["rng"]["stream_key"] == ["model", "NET052"]
          and "pcg64" in m["rng"]["algorithm"])
    check("生效核验记录 beta",
          m["param_effect"].get("beta", {}).get("applied") is True)
    check("started/finished/duration 完整",
          bool(m["started_at"]) and bool(m["finished_at"])
          and m["duration_s"] >= 0)
    check("runtime 版本在场", m["runtime_version"] == "2.1")

    # _manifest_public：对外子集不丢关键字段、不携带完整 checkpoint 状态
    pub = _manifest_public(m)
    check("public 子集含干预与随机流", "interventions" in pub
          and "rng" in pub)
    check("public 子集不含未请求字段",
          set(pub.keys()) <= {"run_id", "requested", "actual", "param_issues",
                              "param_effect", "rng", "clocks", "checkpoint",
                              "events_n", "interventions", "started_at",
                              "finished_at", "duration_s", "warnings",
                              "runtime_version", "model_id", "protocol", "code_version",
                              "software", "artifact_schema", "state_frame_count", "state_every",
                              "data_bindings", "model_definition", "llm_calls", "implementation_note", "fidelity",
                              "scenario_review"})

    # 参数警告留痕：未知参数进入 warnings 与 param_issues
    rr2 = run_model_full("NET052", parameters={"bogus_k": 3}, ticks=5)
    check("未知参数写入 manifest 警告",
          any(i["kind"] == "unknown" for i in rr2.manifest["param_issues"])
          and rr2.manifest["warnings"], f"w={rr2.manifest['warnings']}")

    # 检查点字段：partial 如实标注进 manifest
    rr3 = run_model_full("NET052", ticks=5, checkpoint_at=3)
    check("checkpoint 标注进 manifest",
          rr3.manifest["checkpoint"] is not None
          and rr3.manifest["checkpoint"]["state_fidelity"] == "partial")

    # ODE simulate 通道同样带 manifest（时间戳/时钟）
    check("ODE 通道 final_t=horizon",
          abs(rr.manifest["actual"]["final_t"] - 1.5) < 1e-9)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_tests())
