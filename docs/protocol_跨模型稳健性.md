# 跨模型稳健性协议（消融 C2）——已就绪，待批准执行

> 约束背景：用户指定"只用 QWEN 3.5 4B，别用其他的，其他的太大了，会让电脑卡"。
> 因此本协议的**执行被搁置**；以下内容全部准备就绪，放开约束后一条命令即可。

## 候选模型（LM Studio /v1/models 中已列出）
| 模型 | 大小级 | 与 4B 差距 | 风险 |
|---|---|---|---|
| `qwen/qwen3-vl-4b` | 4B 级（VL 但可纯文本用） | ≈0 | 内存占用与当前模型相当，需同时加载两模型 |
| `qwen/qwen3-8b` | 8B | ×2 | 可能卡顿（用户担心的点） |
| `openai/gpt-oss-20b` | 20B | ×5 | 明确不推荐 |

## 执行命令（批准后）
```bash
python experiments/run_mvp.py --mode llm --agents 200 --ticks 200 \
  --llm-ratio 0.25 --seed 7 --narr-every 8 --narr-sample 24 --workers 6 \
  --model "qwen/qwen3-vl-4b" --tag camp_llm_altmodel_s7
python experiments/compare_runs.py camp_llm_s7 camp_llm_altmodel_s7
```

## 判据
- 结构指标（基尼/工人数/p_ref/剥削率）方向一致性；
- 异化组间排序（受雇>自营 无力感；失业最高）在两个底座上均复现 → 通过；
- 若发散 → 记录为"模型先验依赖"，主结论降格为模型内稳健。

## 注意
- 先 `lms unload` 当前模型或确保显存/内存足够再跑（justInTimeModelLoading=true 会自动加载）；
- 请在电脑空闲时段执行。
