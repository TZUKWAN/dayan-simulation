"""Read-only warnings for pre-contract historical research artifacts."""
import hashlib
import json
import os
from pathlib import Path


def inspect_legacy():
    root=Path(os.environ.get("DAYAN_DATA_DIR", Path(__file__).resolve().parents[2]/"data"))/"collection"
    result={"status":"legacy_unverified", "note":"历史产物保留原文件；没有统一study_id与版本合同，不能替代当前研究。", "files":[], "issues":[]}
    for name in ("usecase1_population.json","replication_pack.json","reports/report_B_academic.md"):
        path=root/name
        if not path.exists():continue
        content=path.read_bytes()
        result["files"].append({"path":name,"sha256":hashlib.sha256(content).hexdigest()})
        if name=="usecase1_population.json":
            obj=json.loads(content);cal=obj.get("calibration",{})
            fitted=set(cal.get("best_params",{}))
            evaluated={tuple(sorted(e.get("params",{}))) for e in cal.get("evaluations",[])}
            if evaluated and tuple(sorted(fitted)) not in evaluated:
                result["issues"].append("历史最优参数与评估记录使用不同模型参数名，不能验证为同一次校准")
            if cal.get("best_loss") is not None and cal.get("baseline_mean_rmse") is not None:
                correct=cal["baseline_mean_rmse"]-cal["best_loss"]
                if abs(correct-cal.get("improvement_vs_baseline",correct))>1e-4:
                    result["issues"].append("历史基线改善量不能由同文件的误差数值复算")
        if name.endswith(".md") and "collection_id=DR-" in content.decode("utf-8"):
            result["issues"].append("历史报告把DataRequirement ID当成collection_id，来源引用未绑定实际采集")
    if result["issues"]:result["status"]="inconsistent_legacy_artifacts"
    return result
