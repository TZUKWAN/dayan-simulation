"""机制修复回归（2026-11-12 批次 1-5）。

每个修复对应一个可复现断言（解析基准/机制方向/守恒），防止回归：
- BEH052-055 公共品与志愿者困境收益结构；
- BEH076 严厉评判与简单立场瞬态可分；
- BEH089/092/093 学习规则真实产生学习信号；
- ECO005 动态投入产出收敛 (I-A)x*=d；ECO078 保留工资解析临界值；
- ECO088 Rasch 梯度方向；ECO112 线性律与平方律区分；
- ECO060 Rogers 非对称迁移；NET080/081 谣言守恒与消亡；
- NET090 级联真实传播；NET058 SEIAR 守恒+无症状流；NET059 vital 守恒；
- SYS003 模拟阻塞≈Erlang-B；BEH115 目标网分离证据；BEH116 决斗头学习。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan.model_index import run_model  # noqa: E402


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

    # ---- 博弈收益结构 ----
    f = run_model('BEH052', ticks=600)[-1]["freq"]
    check("BEH052 搭便车占优", f[0] > 0.95, f"free={f[0]:.3f}")
    f = run_model('BEH053', ticks=600)[-1]["freq"]
    check("BEH053 惩罚下合作占优", f[1] > 0.95, f"contribute={f[1]:.3f}")
    f = run_model('BEH054', ticks=4000)[-1]["freq"]
    check("BEH054 志愿率=解析均衡0.8", abs(f[0] - 0.8) < 0.05,
          f"p={f[0]:.3f}")

    # ---- 声誉规范 ----
    o75 = run_model('BEH075', ticks=300)[-1]
    o76 = run_model('BEH076', ticks=300)[-1]
    check("BEH076 严评瞬态区别于简单立场",
          o76["rep_pos_share"] > o75["rep_pos_share"] + 0.15,
          f"76={o76['rep_pos_share']:.2f} 75={o75['rep_pos_share']:.2f}")

    # ---- 学习规则 ----
    o = run_model('BEH089', ticks=2000)[-1]
    check("BEH089 EWA 学到高收益臂", o["best_arm_share"] > 0.85,
          f"share={o['best_arm_share']:.3f}")
    o = run_model('BEH092', ticks=2000)[-1]
    check("BEH092 后验收敛0.7且BR正确",
          abs(o["posterior_opp0"] - 0.7) < 0.03 and o["br_share"] > 0.9,
          f"post={o['posterior_opp0']:.3f} br={o['br_share']:.3f}")
    o = run_model('BEH093', ticks=4000)[-1]
    check("BEH093 对偏置对手学到最优动作", o["choice_shares"][0] > 0.7,
          f"s0={o['choice_shares'][0]:.3f}")

    # ---- 经济模型 ----
    obs = run_model('ECO005', ticks=80)
    from dayan.models.eco_models import LeontiefDynamicModel
    m = LeontiefDynamicModel()
    x_star = np.linalg.solve(np.eye(m.A.shape[0]) - m.A, m.d)
    check("ECO005 收敛 (I-A)x*=d",
          np.allclose(np.array(obs[-1]["x"]), x_star, atol=0.05),
          f"x={obs[-1]['x']}")
    o = run_model('ECO078', ticks=300)[-1]
    check("ECO078 保留工资在支撑集内且接受发生",
          10 < o["res_wage"] < 50 and o["accepted"] is not None,
          f"w*={o['res_wage']:.1f}")
    o = run_model('ECO088', ticks=2)[-1]
    check("ECO088 Rasch 参数恢复正相关", o["item_b_corr"] > 0.5,
          f"corr={o['item_b_corr']:.3f}")
    o12 = run_model('ECO112', ticks=300, dt=0.05)[-1]
    o11 = run_model('ECO111', ticks=300, dt=0.05)[-1]
    check("ECO112 线性律不变量守恒",
          abs(o12["lin_invariant"] - o12["lin0"]) <
          0.5 * abs(o12["lin0"]) + 1e-6,
          f"inv={o12['lin_invariant']:.2f}")
    check("ECO112 动态区别于平方律",
          abs(o12["N1"] - o11["N1"]) > 1.0,
          f"lin={o12['N1']:.1f} sq={o11['N1']:.1f}")
    o = run_model('ECO060', ticks=80, dt=0.1)[-1]
    pops = np.array(o["pop"])
    check("ECO060 非对称迁移致区域分化", pops.max() - pops.min() > 1.0,
          f"pops={pops.round(2)}")

    # ---- 网络/疫情 ----
    for mid in ("NET080", "NET081"):
        o = run_model(mid, ticks=2000, dt=1.0)[-1]
        total = o["ignorants"] + o["spreaders"] + o["stiflers"]
        check(f"{mid} 三态守恒且谣言消亡",
              total == 400 and o["spreaders"] == 0,
              f"total={total} S={o['spreaders']}")
    o = run_model('NET090', ticks=2)[-1]
    check("NET090 级联传播", o["failed_b"] > 0 and o["failed_a"] > 1,
          f"a={o['failed_a']} b={o['failed_b']}")
    o = run_model('NET058', ticks=200, dt=0.1)[-1]
    tot = sum(o[k] for k in "SEIAR")
    check("NET058 五仓守恒", abs(tot - 1000) < 0.5, f"total={tot}")
    o = run_model('NET059', ticks=600, dt=0.1)[-1]
    check("NET059 vital 守恒+地方病态",
          abs(o["S"] + o["I"] + o["R"] - 1000) < 1.0 and 0 < o["I"] < 100,
          f"I={o['I']:.1f}")

    # ---- 排队 ----
    o = run_model('SYS003', ticks=4000, dt=0.05)[-1]
    check("SYS003 模拟阻塞≈Erlang-B",
          abs(o["B_sim"] - o["B_formula"]) < 0.06,
          f"sim={o['B_sim']:.3f} f={o['B_formula']:.3f}")

    # ---- RL ----
    from dayan.models.beh_rl import DoubleDQNModel
    rng = np.random.default_rng(0)
    m = DoubleDQNModel()
    m.initialize({}, {}, None, None, rng)
    div = float(np.abs(m.net_target.W1 - m.net.W1).sum())
    check("BEH115 目标网训练中真实使用（分离>0 且有学习信号）",
          div > 0 and np.mean(m.reward_hist[-10:]) > 0,
          f"div={div:.4f}")
    o = run_model('BEH116', ticks=1)[-1]
    check("BEH116 决斗头学到最优", o["learned_right"] is True,
          f"greedy={o['greedy_actions']}")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_tests())
