"""DAYAN Agent：意图 → 计划 → 工具执行 → 复核 → 必要时修正规划。

fulfill(text)（WP6 受约束循环，方案 §15）：
  1. plan(text)          规则路由（保底）或 LLM planner（可插拔）
  2. 逐动作 call_tool    确定性执行
  3. 结果回填上下文      run 成功 → 下一轮规划可见（model_id/params/ticks）
  4. 失败 → 修正规划     下一轮重规划；同参数已失败的动作不盲目重试
  5. ok = 全部动作成功   不再"任一成功即整体绿标"（部分失败如实呈现）

LLM 接入方式：set_llm_planner(fn) 后自动切换；
fn 由阿里云 MaaS 客户端实现（读 tool_manifest 做函数调用）。
"""
from __future__ import annotations

import json

from . import intent as _intent
from .tools import TOOL_IMPL, call_tool


def _action_key(action: dict) -> str:
    try:
        return json.dumps([action.get("tool"),
                           sorted((action.get("args") or {}).items(),
                                  key=lambda kv: str(kv[0]))],
                          ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(action)


class DayanAgent:
    name = "DAYAN Agent"

    def __init__(self, max_actions=4, max_rounds=3):
        self.max_actions = max_actions
        self.max_rounds = max_rounds

    def fulfill(self, text, history=None, last_run=None, progress=None):
        executed = []
        attempted: set[str] = set()
        rounds = []
        ctx_run = dict(last_run or {})       # 结构化上下文（供下一轮规划）
        if ctx_run.get("run_id"):
            try:
                from .context import canonical_context
                ctx_run=canonical_context(ctx_run)
            except (ValueError,KeyError,FileNotFoundError) as exc:
                return {"ok":False,"planner":"context-check","intent":None,"plan":[],"executed":[],
                        "errors":["上次运行上下文无法核验："+str(exc)]}
        last_planning: dict = {}
        planning_errors = []
        feedback = []
        for round_i in range(self.max_rounds):
            last_planning = _intent.plan(text, history=history,
                                         last_run=ctx_run, feedback=feedback)
            planning_errors = last_planning.get("errors", [])
            plan = last_planning.get("plan", [])[: self.max_actions]
            # 跳过：已成功的动作不重复；同参数已失败的动作不盲目重试
            done_keys = {_action_key(e) for e in executed if e.get("ok")}
            fail_keys = {_action_key(e) for e in executed if not e.get("ok")}
            todo = []
            for a in plan:
                k = _action_key(a)
                if k in done_keys or k in fail_keys:
                    continue
                todo.append(a)
            if not todo:
                break
            rounds.append({"round": round_i,
                           "planner": last_planning.get("planner"),
                           "intent": last_planning.get("intent"),
                           "plan": todo})
            if progress and round_i > 0:
                progress(f"第 {round_i + 1} 轮修正规划（基于上轮结果）")
            need_replan = False
            for action in todo:
                tool = action.get("tool")
                args = action.get("args") or {}
                attempted.add(_action_key(action))
                if progress:
                    mid = args.get("model_id") if isinstance(args, dict) else None
                    progress(f"执行 {tool}" + (f" {mid}" if mid else "") + " …")
                if tool not in TOOL_IMPL:
                    executed.append({"tool": tool, "ok": False,
                                     "error": "未知工具"})
                    need_replan = True
                    continue
                try:
                    from .progress import progress_scope
                    with progress_scope(progress):result = call_tool(tool, **args)
                except Exception as e:                     # noqa: BLE001
                    # LLM 计划畸形（args 非字典/缺参/类型错）不得穿透成 500
                    executed.append({"tool": tool, "args": args, "ok": False,
                                     "error": f"{type(e).__name__}: {e}"})
                    need_replan = True
                    continue
                entry = {"tool": tool, "args": args, **result}
                if entry.get("ok") and isinstance(entry.get("payload"),dict) and tool in ("run","resume","build_model","sweep","ensemble","experiment","compare"):
                    from ..scene_contract import check_saved_scene
                    payload=entry["payload"];targets=[payload] if payload.get("run_id") else payload.get("runs",[])
                    alignments=[]
                    for target in targets:
                        try:alignment=check_saved_scene(last_planning.get("requirements") or {},target)
                        except (ValueError,KeyError,FileNotFoundError) as exc:
                            alignment={"status":"mismatch","issues":["实际归档场景核验失败："+str(exc)]}
                        alignments.append({"run_id":target.get("run_id"),**alignment})
                    issues=[issue for a in alignments for issue in a["issues"]]
                    if alignments:payload["scene_alignment"]={**alignments[0],"issues":issues,"runs":alignments}
                    if issues:entry.update(ok=False,error="实际结果与用户场景不对应："+"；".join(dict.fromkeys(issues)))
                executed.append(entry)
                if progress and entry.get("ok") \
                        and isinstance(entry.get("payload"), dict) \
                        and entry["payload"].get("n"):
                    progress(f"{tool} 完成（{entry['payload']['n']} obs）")
                # 失败 → 触发修正规划；成功 run → 回填结构化上下文
                if not entry.get("ok"):
                    need_replan = True
                elif tool in ("run","resume","build_model","sweep","ensemble","experiment","compare") and isinstance(entry.get("payload"), dict):
                    p = entry["payload"]
                    if not p.get("manifest") and p.get("runs"):
                        from ..run_store import get_store
                        saved=get_store().load(p["runs"][0]["run_id"])
                        p={"run_id":saved["run_id"],"model_id":saved["model_id"],"manifest":saved["manifest"],"n":len(saved.get("observations",[]))}
                    ctx_run = {"model_id": p.get("model_id"),
                               "ticks": p.get("manifest", {}).get("requested", {}).get("ticks"),
                               "dt": p.get("manifest", {}).get("requested", {}).get("dt"),
                               "seed": p.get("manifest", {}).get("rng", {}).get("seed"),
                               "params": p.get("manifest", {}).get("actual", {}).get("effective_parameters") or {},
                               "manifest": p.get("manifest", {}),
                               "run_id": p.get("run_id"),
                               "n_obs": p.get("n")}
                p = entry.get("payload") or {}
                read_metadata=tool in ('search_models','get_capabilities')
                feedback.append({"tool": tool, "args": args, "ok": entry.get("ok"),
                                 "error": entry.get("error"),
                                 "result": p if read_metadata else {k: p[k] for k in ("model_id", "run_id", "analysis_id", "experiment_id", "warnings", "analysis", "dataset_id", "preview", "fields", "numeric", "definition") if isinstance(p, dict) and k in p}
                                 if isinstance(p, dict) else p})
                # 搜索结果产生后再规划依赖它的动作，不能执行“待返回后确定”的占位ID。
                if tool == "search_models":
                    need_replan = need_replan or action != todo[-1]
                    break
            expected_run = (last_planning.get("requirements") or {}).get("kind") in ("run", "resume", "experiment", "sweep", "ensemble", "compare", "compose", "build_model")
            has_run = any(e.get("ok") and isinstance(e.get("payload"), dict) and (e["payload"].get("run_id") or e["payload"].get("runs")) for e in executed)
            if expected_run and not has_run:
                need_replan = True
            if not need_replan and not last_planning.get("continue"):
                break
        requirements = last_planning.get("requirements") or {}
        if requirements.get("kind") in ("run", "resume", "experiment", "sweep", "ensemble", "compare", "compose", "build_model") and not any(
                e.get("ok") and isinstance(e.get("payload"), dict) and (e["payload"].get("run_id") or e["payload"].get("runs")) for e in executed):
            planning_errors = list(planning_errors) + ["尚未产生对应需求的实际模型运行结果"]
        return {
            "planner": (rounds[-1]["planner"] if rounds
                        else last_planning.get("planner", "rule")),
            "intent": (rounds[-1]["intent"] if rounds
                       else last_planning.get("intent")),
            "scene": next((e["payload"].get("scene_alignment") for e in reversed(executed) if e.get("ok") and isinstance(e.get("payload"),dict) and e["payload"].get("scene_alignment")),None),
            "plan": [a for r in rounds for a in r["plan"]],
            "rounds": rounds,
            "executed": executed,
            "errors": planning_errors,
            "requirements": last_planning.get("requirements"),
            "constraint_corrections": last_planning.get("constraint_corrections", []),
            "planner_error": last_planning.get("planner_error"),
            # 诚实判定：任一动作失败即整体失败，不再"任一成功即 ok"
            "ok": bool(executed) and not planning_errors and all(e.get("ok") for e in executed),
        }

    @staticmethod
    def summarize(fulfill_result, max_rows=6):
        """给前端的紧凑摘要（不吐全量 JSON）。"""
        rows = []
        if fulfill_result.get("planner_error"):rows.append("✗ 规划未完成："+str(fulfill_result["planner_error"]))
        rows.extend("✗ " + str(error) for error in fulfill_result.get("errors", []))
        for e in fulfill_result.get("executed", []):
            if not e.get("ok"):
                rows.append(f"✗ {e['tool']}: {e.get('error', '失败')}")
                continue
            p = e.get("payload", {})
            if e["tool"] in ("run","resume"):
                obs = p.get("observations", [])
                last = obs[-1] if obs else {}
                keys = [k for k, v in last.items()
                        if isinstance(v, (int, float))][:4]
                row = (f"✓ {e['tool']} {p.get('model_id')}（{p.get('n')} obs） "
                       + " ".join(f"{k}={last[k]}" for k in keys))
                warns = []
                if p.get("ignored_params"):
                    warns.append(f"已忽略未知参数 {p['ignored_params']}")
                if p.get("coerced_params"):
                    warns.append(f"已取整参数 {p['coerced_params']}")
                if warns:
                    row += "  ⚠ " + "；".join(warns)
                rows.append(row)
            elif e["tool"] == "search_models":
                caps = p.get("matches", []) if isinstance(p, dict) else p if isinstance(p, list) else []
                ids = [c["model_id"] for c in caps[:6]]
                rows.append(f"✓ search {len(caps)} 个匹配: {', '.join(ids)}")
            elif e["tool"] == "sweep":
                runs = p.get("runs", [])
                seg = "; ".join(f"{r['value']}→{list(r['final'].items())[:1]}"
                                for r in runs[:4])
                row = f"✓ sweep {p.get('model_id')}.{p.get('param')}: {seg}"
                if p.get("ignored_params"):
                    row += f"  ⚠ 参数 {p['ignored_params']} 不在此模型能力卡上，结果可能无差异"
                rows.append(row)
            elif e["tool"] == "ensemble":
                stats = p.get("stats", {})
                seg = "; ".join(f"{k}: μ={v['mean']:.3f} σ={v['std']:.3f}"
                                for k, v in list(stats.items())[:3])
                rows.append(f"✓ ensemble {p.get('model_id')}（{p.get('n_seeds')} 种子）{seg}")
            elif e["tool"] == "compare":
                if p.get("note"):
                    rows.append(f"⚠ compare {p.get('mid_a')} vs {p.get('mid_b')}: {p['note']}")
                else:
                    rows.append(f"✓ compare {p.get('mid_a')} vs {p.get('mid_b')}: "
                                f"{p.get('shared_fields')}")
            elif e["tool"] == "compose":
                rows.append(f"✓ compose {p.get('n_stages')} 级流水线完成")
            elif e["tool"] == "experiment":
                a = p.get("analysis") or {}
                base = a.get("baseline_window_mean")
                arms_txt = []
                for lbl, s in (a.get("arms") or {}).items():
                    pdm = (s.get("paired_diff") or {}).get("mean")
                    if pdm is not None:
                        arms_txt.append(f"{lbl}: Δ={pdm:.4g}")
                rows.append(f"✓ experiment {a.get('model_id')} 指标 {a.get('metric')}"
                            + (f" 基线={base:.4g}" if isinstance(base, (int, float))
                               else "")
                            + ("；" + "；".join(arms_txt) if arms_txt
                               else "（仅基线重复）"))
            elif e["tool"] == "get_capabilities":
                c = p
                rows.append(f"✓ 能力卡 {c.get('model_id')}: 参数="
                            f"{[x['name'] for x in c.get('parameters', [])]}, "
                            f"观测量={c.get('observables', [])[:5]}")
            elif e["tool"] == "build_model":
                count=f"{len(p['runs'])}个种子运行" if p.get("result_kind")=="ensemble" else f"{p.get('n')}条观测"
                rows.append(f"✓ 新模型 {p.get('model_id')} 已实际执行，{count}；定义与状态已归档")
            elif e["tool"] == "explain":
                rows.append(p.get("reply","未生成解释"))
            elif e["tool"] == "collect_data":
                rows.append(f"✓ 数据集 {p.get('dataset_id')} 已取得并保存原始文件；来源 {p.get('source')}")
            elif e["tool"] == "analyze_data":
                rows.append(f"✓ 数据分析 {p.get('dataset_id')}：{p.get('n_rows')}条记录，{len(p.get('numeric', {}))}个数值字段")
        if not rows:
            rows.append("（无动作执行）")
        return rows[:max_rows]


def get_agent():
    return DayanAgent()
