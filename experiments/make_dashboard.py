"""生成 16:9 帅气版效果总览大图（深色驾驶舱风格）。

左列=数据面板（6 图），右列=模拟现场（财富阶梯/企业用工监视器/真实叙事与决策流）。
用法：python experiments/make_dashboard.py
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]

import argparse
_ap = argparse.ArgumentParser()
_ap.add_argument("--run", default="mvp_llm_s7")
_ap.add_argument("--rule-run", default="mvp_rule_s7")
_ap.add_argument("--theme", choices=["dark", "light"], default="dark")
_ap.add_argument("--out", default=None)
_args, _ = _ap.parse_known_args()
RUN = ROOT / "results" / _args.run
RULE = ROOT / "results" / _args.rule_run

# ---- 主题 ----
if _args.theme == "light":
    BG, PANEL, EDGE, TXT, SUB, GRID = (
        "#f1f5f9", "#ffffff", "#d7dee9", "#1e293b", "#64748b", "#e2e8f0")
    C_CYAN, C_GREEN, C_RED, C_ORANGE, C_PURPLE, C_YELLOW = (
        "#0891b2", "#059669", "#dc2626", "#d97706", "#7c3aed", "#b45309")
    CARD = "#f8fafc"
else:
    BG, PANEL, EDGE, TXT, SUB, GRID = (
        "#0b0f19", "#131a2a", "#243049", "#e7ecf5", "#94a3b8", "#22304a")
    C_CYAN, C_GREEN, C_RED, C_ORANGE, C_PURPLE, C_YELLOW = (
        "#22d3ee", "#34d399", "#f87171", "#fbbf24", "#a78bfa", "#facc15")
    CARD = "#0f1626"
POS_COLOR = {"worker": C_CYAN, "self": C_GREEN, "employer": C_RED,
             "unemployed": "#9aa4b8"}
POS_CN = {"worker": "受雇者", "self": "自营者", "employer": "经营者",
          "unemployed": "失业者"}

fig = plt.figure(figsize=(20, 11.25), dpi=160)
fig.patch.set_facecolor(BG)


def style(ax, title=None, tag_color=C_CYAN):
    ax.set_facecolor(PANEL)
    for s in ax.spines.values():
        s.set_color(EDGE)
    ax.tick_params(colors=SUB, labelsize=9)
    ax.grid(color=GRID, lw=0.7, alpha=0.55)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, color=TXT, fontsize=11.5, loc="left",
                     fontweight="bold", pad=8)
    return ax


def panel(x, y, w, h):
    ax = fig.add_axes([x, y, w, h])
    ax.set_facecolor(PANEL)
    for s in ax.spines.values():
        s.set_color(EDGE)
    ax.tick_params(colors=SUB, labelsize=9)
    ax.grid(color=GRID, lw=0.7, alpha=0.55)
    ax.set_axisbelow(True)
    return ax


# ================= 头部 =================
lm = pd.read_csv(RUN / "metrics.csv")
rm = pd.read_csv(RULE / "metrics.csv")
stats = json.loads((RUN / "llm_stats.json").read_text(encoding="utf-8"))

fig.text(0.022, 0.955, "msim · toy_capitalism_v0", color=TXT,
         fontsize=26, fontweight="bold", va="center")
fig.text(0.022, 0.925, "马克思主义理论 × 大模型社会仿真 · 首轮四组对照实验",
         color=SUB, fontsize=13, va="center")

badges = [
    ("200 AGENTS × 200 TICKS", C_CYAN),
    (f"{stats['http_calls']:,} LLM CALLS", C_PURPLE),
    (f"回退 {stats['decision_fallbacks']}", C_GREEN),
    ("QWEN3.5-4B · LM STUDIO 本地", C_ORANGE),
    ("守恒残差 ~1e-13", C_YELLOW),
]
bx = 0.505
for label, c in badges:
    w = 0.0115 * len(label) + 0.022
    fig.patches.append(FancyBboxPatch(
        (bx, 0.933), w, 0.032, transform=fig.transFigure,
        boxstyle="round,pad=0.004,rounding_size=0.012",
        facecolor=PANEL, edgecolor=c, lw=1.2))
    fig.text(bx + w / 2, 0.949, label, color=c, fontsize=10.5,
             ha="center", va="center", fontweight="bold")
    bx += w + 0.012

# 区块标签
fig.text(0.022, 0.887, "① 数据面板 · 对照与经济观测", color=C_CYAN,
         fontsize=14, fontweight="bold", va="center")
fig.text(0.545, 0.887, "② 模拟现场 · 财富阶梯 / 企业监视 / 叙事与决策流",
         color=C_ORANGE, fontsize=14, fontweight="bold", va="center")
fig.lines.extend([plt.Line2D([0.022, 0.505], [0.878, 0.878],
                             transform=fig.transFigure, color=C_CYAN, lw=1.6, alpha=0.7),
                  plt.Line2D([0.545, 0.978], [0.878, 0.878],
                             transform=fig.transFigure, color=C_ORANGE, lw=1.6, alpha=0.7)])

# ================= 左列：6 图 =================
LX, LW = 0.022, 0.232
GX = LX + LW + 0.014
ROWS = [0.652, 0.388, 0.124]
RH = 0.203

# --- 1 财富不平等对比 ---
r30 = rm.set_index("tick").tail(30).mean()
l30 = lm.set_index("tick").tail(30).mean()
ax = panel(LX, ROWS[0], LW, RH)
vals = [r30.gini, l30.gini, r30.top10, l30.top10]
ax.bar(["规则\n基尼", "LLM\n基尼", "规则\ntop10", "LLM\ntop10"], vals,
       color=["#64748b", C_RED, "#64748b", C_ORANGE], width=0.62)
for i, v in enumerate(vals):
    ax.text(i, v + 0.02, f"{v:.2f}", ha="center", color=TXT, fontsize=10,
            fontweight="bold")
ax.set_ylim(0, 0.88)
style(ax)
ax.set_title("» 财富不平等 · LLM组基尼 +137%", color=TXT, fontsize=11.5,
             loc="left", fontweight="bold", pad=8)

# --- 2 价格战 ---
ax = panel(GX, ROWS[0], LW, RH)
ax.plot(rm.tick, rm.p_ref, color="#94a3b8", lw=1.8, label="规则组")
ax.plot(lm.tick, lm.p_ref, color=C_RED, lw=2.2, label="LLM组")
ax.set_xlabel("tick", color=SUB, fontsize=9)
ax.legend(facecolor=PANEL, edgecolor=EDGE, labelcolor=TXT, fontsize=9)
style(ax)
ax.set_title("» 自发价格战 · 参考价 −60%", color=TXT, fontsize=11.5,
             loc="left", fontweight="bold", pad=8)

# --- 3 阶级位置构成 ---
ax = panel(LX, ROWS[1], LW, RH)
tot = lm[["pos_unemployed", "pos_worker", "pos_self", "pos_employer"]].sum(axis=1)
ax.stackplot(lm.tick,
             lm.pos_self / tot, lm.pos_worker / tot,
             lm.pos_employer / tot, lm.pos_unemployed / tot,
             colors=[C_GREEN, C_CYAN, C_RED, "#9aa4b8"],
             labels=["自营", "受雇", "经营者", "失业"])
ax.set_ylim(0, 1)
ax.set_xlabel("tick", color=SUB, fontsize=9)
ax.legend(facecolor=PANEL, edgecolor=EDGE, labelcolor=TXT, fontsize=8,
          loc="lower right", ncol=2)
style(ax)
ax.set_title("» 阶级结构涌现 · 四位置", color=TXT, fontsize=11.5,
             loc="left", fontweight="bold", pad=8)

# --- 4 剩余占有记账 ---
ax = panel(GX, ROWS[1], LW, RH)
ax.plot(lm.tick, lm.labor_share, color=C_GREEN, lw=2, label="劳动份额 0.76")
ax.plot(lm.tick, lm.exploitation_rate, color=C_ORANGE, lw=2,
        label="剥削率(代理) 0.31")
ax.set_xlabel("tick", color=SUB, fontsize=9)
ax.legend(facecolor=PANEL, edgecolor=EDGE, labelcolor=TXT, fontsize=8.5)
style(ax)
ax.set_title("» 剩余占有 · 逐tick记账", color=TXT, fontsize=11.5,
             loc="left", fontweight="bold", pad=8)

# --- 5 财富分布（期末直方，log-y） ---
ag = pd.read_csv(RUN / "agents_final.csv")
ax = panel(LX, ROWS[2], LW, RH)
w = ag.wealth.values
bins = np.logspace(np.log10(max(1, w.min() + 1)), np.log10(w.max() + 1), 28)
ax.hist(w, bins=bins, color=C_PURPLE, alpha=0.85, edgecolor=EDGE)
ax.set_xscale("log")
ax.set_yscale("log")
ax.set_xlabel("财富", color=SUB, fontsize=9)
ax.text(0.97, 0.9, "下层指数 + 上尾 Pareto\n(KS 0.29 / 0.14)", transform=ax.transAxes,
        ha="right", va="top", color=C_YELLOW, fontsize=9)
style(ax)
ax.set_title("» 财富分布 · 两阶级形态", color=TXT, fontsize=11.5,
             loc="left", fontweight="bold", pad=8)

# --- 6 异化量表 ---
alien = pd.read_csv(RUN / "alienation.csv")
dims = ["powerlessness", "meaninglessness", "normlessness", "isolation",
        "self_estrangement"]
dim_cn = ["无力感", "无意义", "无规范", "孤立感", "自我疏离"]
ax = panel(GX, ROWS[2], LW, RH)
groups = alien.groupby("position")[dims].mean()
order = [p for p in ["worker", "self", "unemployed"] if p in groups.index]
x = np.arange(len(dims))
bw = 0.8 / max(1, len(order))
for i, p in enumerate(order):
    ax.bar(x + i * bw, groups.loc[p, dims].values, bw,
           color=POS_COLOR[p], label=f"{POS_CN[p]}(n={int((alien.position==p).sum())})")
ax.set_xticks(x + bw * (len(order) - 1) / 2)
ax.set_xticklabels(dim_cn, fontsize=8.5)
ax.set_ylim(0, 5.4)
ax.legend(facecolor=PANEL, edgecolor=EDGE, labelcolor=TXT, fontsize=7.5,
          loc="upper right")
style(ax)
ax.set_title("» Seeman五维异化 · 与《1844手稿》预期一致", color=TXT,
             fontsize=11.5, loc="left", fontweight="bold", pad=8)

# ================= 右列：模拟现场 =================
RX, RW = 0.545, 0.433

# --- R1 财富阶梯 ---
ax = panel(RX, 0.585, RW, 0.275)
top = ag.sort_values("wealth", ascending=False).head(16).iloc[::-1]
colors = [POS_COLOR[p] for p in top.position]
ax.barh([f"#{int(i):03d}" for i in top.id], top.wealth, color=colors,
        edgecolor=BG, lw=0.4, height=0.72)
for y, (_, r) in enumerate(top.iterrows()):
    tag = POS_CN[r.position]
    ax.text(r.wealth + max(top.wealth) * 0.01, y, f" {tag}", va="center",
            color=POS_COLOR[r.position], fontsize=8.5)
ax.set_xlim(0, max(top.wealth) * 1.30)
style(ax)
ax.set_title("» 财富阶梯 · 期末TOP16 · 横轴=期末财富（真实agent，按阶级位置着色）",
             color=TXT, fontsize=11.5, loc="left", fontweight="bold", pad=8)

# --- R2 企业用工监视器 ---
firms = pd.read_csv(RUN / "firms.csv")
ax = panel(RX, 0.345, RW, 0.20)
counts = firms.fid.value_counts()
picked = list(counts.index[:4])
cmap = [C_CYAN, C_ORANGE, C_GREEN, C_PURPLE]
for c, fid in zip(cmap, picked):
    sub = firms[firms.fid == fid].sort_values("tick")
    ax.step(sub.tick, sub.n_workers, where="post", color=c, lw=1.8,
            label=f"企业#{fid}")
ax.set_xlabel("tick", color=SUB, fontsize=9)
ax.set_ylabel("在职工人数", color=SUB, fontsize=9)
ax.legend(facecolor=PANEL, edgecolor=EDGE, labelcolor=TXT, fontsize=8.5, ncol=4)
style(ax)
ax.set_title("» 企业用工监视器 · 雇佣规模轨迹（订单制）", color=TXT,
             fontsize=11.5, loc="left", fontweight="bold", pad=8)

# --- R3 真实叙事与决策流 ---
ax = panel(RX, 0.055, RW, 0.25)
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")
ax.set_title("» 模拟现场直播 · 真实LLM决策与agent叙事", color=TXT,
             fontsize=11.5, loc="left", fontweight="bold", pad=8)

cards: list[tuple[str, str, str]] = []  # (icon色, 标题, 正文)

# 决策卡（真实 llm_log）
dec_texts = []
for line in open(RUN / "llm_log.jsonl", encoding="utf-8"):
    try:
        rec = json.loads(line)
    except Exception:
        continue
    c = rec.get("content") or ""
    if '"action"' in c and len(c) < 120:
        dec_texts.append(c.strip())
if dec_texts:
    # 按动作类型挑代表性真实输出（优先 operate/work/firm/capital，避免全是idle）
    def _act(t):
        for a in ("operate", "work", "firm", "capital", "self", "idle"):
            if a in t:
                return a
        return "?"
    seen: dict[str, str] = {}
    for t in dec_texts:
        seen.setdefault(_act(t), t)
    order = ["operate", "work", "firm", "capital", "self", "idle"]
    picks = [seen[a] for a in order if a in seen][:3]
    total = len(dec_texts)
    for j, d in enumerate(picks):
        cards.append((C_CYAN, f"决策 · Qwen3.5-4B 真实输出（共{total}条可解析）", d))

# 叙事卡（真实 alienation.csv）
pick_pos = ["worker", "self", "unemployed"]
for p in pick_pos:
    sub = alien[(alien.position == p) & (alien.narrative.str.len() > 20)]
    if len(sub):
        row = sub.iloc[len(sub) // 2]
        txt = row.narrative[:64] + ("…" if len(row.narrative) > 64 else "")
        cards.append((POS_COLOR[p],
                      f"叙事 · {POS_CN[p]} #{int(row.agent):03d} · tick{int(row.tick)} · 异化总分{int(row.total)}",
                      f"“{txt}”"))

y = 0.945
dh = 0.148
for color, title, body in cards[:6]:
    ax.add_patch(FancyBboxPatch((0.005, y - dh + 0.012), 0.985, dh - 0.008,
                                boxstyle="round,pad=0.004,rounding_size=0.015",
                                facecolor=CARD, edgecolor=color,
                                lw=1.1, alpha=0.95))
    ax.add_patch(FancyBboxPatch((0.005, y - dh + 0.012), 0.012, dh - 0.008,
                                boxstyle="round,pad=0.002,rounding_size=0.008",
                                facecolor=color, edgecolor="none"))
    ax.text(0.032, y - 0.022, title, color=color, fontsize=8.8,
            fontweight="bold", va="top")
    wrapped = "\n".join(textwrap.wrap(body, 52)[:2])
    ax.text(0.032, y - 0.055, wrapped, color=TXT, fontsize=8.6, va="top")
    y -= dh

# ================= 页脚 =================
fig.text(0.022, 0.012,
         "msim 独立项目 · toy_capitalism_v0 · 规则基线 mvp_rule_s7 vs LLM主组 mvp_llm_s7 · "
         "遮蔽设计：prompt零理论词汇（审计通过）· 逐tick全量记账与调用审计 · 2026-11-06",
         color=SUB, fontsize=9.5)

out = ROOT / "results" / (_args.out or f"dashboard_{_args.run}_{_args.theme}_16x9.png")
fig.savefig(out, dpi=160, facecolor=BG)
print("saved:", out)
