# %% [markdown]
# # P1 统计工具自检
#
# 检查 `notebooks/erp_lib.py` 新增的 P1 工具（`docs/research/erp-phase2-plan.md` P1 节）：
#
# - A 与旧运行 `05cf3475b6354fa8be2c4d3f7bab942f` 的 `oos.csv` 逐项比对 `oos_expanding`
# - B IVX 规模（φ = 0.99、扰动相关 −0.9、n = 250、2000 次）：5% 拒绝率必须落在 3%–8%
# - C IVX 势（只报告）
# - D 零假设自助法规模粗检（只报告）
# - E 平稳自助法索引的平均块长
# - F 真实数据（000985、V）的 IVX 与 NW t（只打印不判读）
#
# 研究用自检：只 print 与 assert，不写库、不落 run log。

# %%
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from erp_lib import (
    clark_west_np,
    forward_sum,
    ivx_wald,
    moving_block_indices,
    null_bootstrap_draw,
    nw_ols,
    oos_expanding,
    r2_os,
    stationary_indices,
)

pd.set_option("display.width", 200)

RUN = Path("/Volumes/QuantDB/quantagent/var/research/erp_rate_anchor/05cf3475b6354fa8be2c4d3f7bab942f")
MAIN = "000985.CSI"
HORIZONS = (1, 3, 6, 12)
MIN_HISTORY = 36
OOS_START = "2012-12"
SEED = 20261124
N_SIM = 2000
Z_975 = 1.959963984540054


def hdr(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}", flush=True)


# %% [markdown]
# ## A. `oos_expanding` 与旧实现逐项一致
#
# 旧 `oos_forecasts` 的训练集「已实现」判断走的是日期：`realized[q] = 第 q+h 月的首个交易日`，
# 要求 `realized[q] <= 信号日`。第 q+h+1 月的首个交易日必然晚于第 i 月的最后一个交易日，
# 所以上界是 `q <= i−h−1`（不是 `i−h`）。`oos_expanding` 按原代码语义实现，
# 用 `i−h` 会让 h=12 的 R²_OS 偏 +0.028。

# %%
hdr("A. oos_expanding  vs  旧 run oos.csv")
monthly = pd.read_csv(RUN / "monthly.csv", float_precision="round_trip")
oos_old = pd.read_csv(RUN / "oos.csv")
oos_start = int(np.flatnonzero(monthly["period"].to_numpy() == OOS_START)[0])
print(f"样本 {len(monthly)} 个月，oos_start = {OOS_START} → 位置 {oos_start}")

rows = []
for h in HORIZONS:
    yh = monthly[f"fwd{h}|{MAIN}"].to_numpy()
    for model, col in (("M1_V", f"V|{MAIN}"), ("M_EY", f"ey|{MAIN}")):
        X = monthly[[col]].to_numpy()
        fc = oos_expanding(
            yh, X, h, train_start=0, oos_start=oos_start, min_history=MIN_HISTORY
        ).dropna()
        r2 = r2_os(fc["y"], fc["model"], fc["M0"])
        cw_t, cw_p = clark_west_np(fc["y"], fc["M0"], fc["model"], h)
        old = oos_old[
            (oos_old["index"] == MAIN)
            & (oos_old["h"] == h)
            & (oos_old["model"] == model)
            & (oos_old["vs"] == "M0")
        ].iloc[0]
        rows.append(
            {
                "h": h,
                "model": model,
                "n": len(fc),
                "n_old": int(old["n"]),
                "r2": r2,
                "r2_old": old["r2_oos"],
                "cw_t": cw_t,
                "cw_t_old": old["cw_t"],
                "d_r2": r2 - old["r2_oos"],
                "d_cw_t": cw_t - old["cw_t"],
            }
        )
chk_a = pd.DataFrame(rows)
print(chk_a.round(12).to_string(index=False))
worst = max(chk_a["d_r2"].abs().max(), chk_a["d_cw_t"].abs().max())
print(f"最大绝对差 = {worst:.3e}（阈值 1e-9）")
assert (chk_a["n"] == chk_a["n_old"]).all(), "样本月份数不一致"
assert worst < 1e-9, "oos_expanding 与旧实现不一致"
print("A 通过")


# %% [markdown]
# ## B / C 的 DGP
#
# 预测回归：`y1[t] = β·x[t] + ε[t]`，`x[t] = 0.99·x[t−1] + u[t]`，`(ε, u)` 标准正态、相关 −0.9。
#
# 扰动的对齐方式是 Stambaugh / Kostakis-Magdalinos-Stamatogiannis（2015）的口径：
# `y1[t]` 是 x[t] 之后那个月的收益，与它同期的是 x 从 t 到 t+1 的更新 `u[t+1]`
# （即 `x[t+1] − 0.99·x[t]`），所以 `corr(ε[t], u[t+1]) = −0.9`。
# 若按字面把 `ε[t]` 与 `u[t]`（进入 x[t] 的那个更新）对齐，x[t] 就与 y1[t] 同期相关，
# 那是永久的联立内生性，任何用 Δx 构造的工具都救不回来，IVX 规模必然崩（实测拒绝率 79%）。
# 本研究笔记里「扰动相关 −0.9」指的就是 Stambaugh 那个相关，故按此实现。

# %%
def dgp(n: int, rng: np.random.Generator, *, beta: float = 0.0, phi: float = 0.99,
        rho: float = -0.9) -> tuple[np.ndarray, np.ndarray]:
    z = rng.standard_normal((2, n + 1))
    u = z[0]  # u[t] 用于 x[t]，t = 0..n
    e = rho * z[0][1:] + np.sqrt(1 - rho**2) * z[1][1:]  # e[t] 与 u[t+1] 相关
    x = np.empty(n)
    x[0] = rng.standard_normal() / np.sqrt(1 - phi**2)  # 从平稳分布起步
    for t in range(1, n):
        x[t] = phi * x[t - 1] + u[t]
    return beta * x + e, x


def nw_t_both(y1: np.ndarray, x: np.ndarray, h: int) -> float:
    """``yh ~ 1 + x`` 的 NW t 值（滞后 h）。"""
    yh = forward_sum(y1, h)
    fit, _ = nw_ols(pd.Series(yh, name="y"), pd.DataFrame({"x": x}), h)
    return float(fit.tvalues["x"])


def check_dgp(n: int = 250, n_rep: int = 400) -> None:
    """DGP 自检：估计 φ、corr(ε, u 的一期更新)、x 的方差。"""
    rng = np.random.default_rng(SEED)
    phis, rhos, sds = [], [], []
    for _ in range(n_rep):
        y1, x = dgp(n, rng)
        phis.append(np.polyfit(x[:-1], x[1:], 1)[0])
        # y1[t] 与 x[t+1]−0.99·x[t] 的相关
        rhos.append(np.corrcoef(y1[:-1], x[1:] - 0.99 * x[:-1])[0, 1])
        sds.append(x.std())
    print(
        f"DGP 自检（{n_rep} 条路径, n={n}）：φ̂={np.mean(phis):.3f}（OLS 向下偏，理论偏幅 −(1+3φ)/n ≈ "
        f"{(1 + 3 * 0.99) / n:.3f}）  corr(ε_t, Δx 的一期更新)={np.mean(rhos):+.3f}  "
        f"样本 sd(x) 均值={np.mean(sds):.2f}（平稳分布 sd {1 / np.sqrt(1 - 0.99**2):.2f}；n=250 时样本"
        f" sd 系统性偏小）"
    )


check_dgp()

# %% [markdown]
# ## B. IVX 规模

# %%
hdr("B. IVX 规模：y1 = ε，5% 拒绝率（必须落在 3%–8%）")
rows = []
for h in (1, 12):
    rng = np.random.default_rng(SEED)
    rej_ivx, rej_nw = [], []
    for _ in range(N_SIM):
        y1, x = dgp(250, rng)
        rej_ivx.append(ivx_wald(y1, x, h)["p"] < 0.05)
        rej_nw.append(abs(nw_t_both(y1, x, h)) > Z_975)
    rows.append(
        {"h": h, "n_sim": N_SIM, "ivx_rej5": np.mean(rej_ivx), "nw_two_sided_rej5": np.mean(rej_nw)}
    )
size = pd.DataFrame(rows)
print(size.round(4).to_string(index=False))
for _, r in size.iterrows():
    ok = 0.03 <= r["ivx_rej5"] <= 0.08
    print(f"  h={int(r['h']):2d}  IVX 拒绝率 {r['ivx_rej5']:.4f} → {'在 [0.03, 0.08] 内' if ok else '超界'}")
    assert ok, f"h={int(r['h'])} 的 IVX 规模 {r['ivx_rej5']:.4f} 不在 [0.03, 0.08]，停止（不调参凑）"
print("B 通过")


# %% [markdown]
# ## C. IVX 势（只报告）
#
# 同 DGP，`y1[t] = 0.05·x[t] + ε[t]`。用同一个种子，所以与 B 的路径逐条配对。

# %%
hdr("C. IVX 势：y1 = 0.05·x + ε，5% 拒绝率（只报告）")
rows = []
for h in (1, 12):
    rng = np.random.default_rng(SEED)
    rej_ivx, rej_nw = [], []
    for _ in range(N_SIM):
        y1, x = dgp(250, rng, beta=0.05)
        rej_ivx.append(ivx_wald(y1, x, h)["p"] < 0.05)
        rej_nw.append(abs(nw_t_both(y1, x, h)) > Z_975)
    rows.append(
        {
            "h": h,
            "n_sim": N_SIM,
            "ivx_rej5": np.mean(rej_ivx),
            "nw_two_sided_rej5": np.mean(rej_nw),
            "beta": 0.05,
        }
    )
power = pd.DataFrame(rows)
print(power.round(4).to_string(index=False))
print("（只报告，不判读；β·sd(x)/sd(ε) = 0.05 × 7.09 = 0.35）")


# %% [markdown]
# ## D. 零假设自助法规模粗检（只报告）
#
# 在 B 的 DGP 下：`y1 = ε`，`X` 走 AR(1)。`null_bootstrap_draw` 用受限模型（只有截距）的残差
# 与 x 的 VAR(1) 残差按行配对，再用 `stationary_indices(mean_block=12)` 联合重抽。
# 统计量是 `yh(12) ~ x` 的 NW t。

# %%
hdr("D. 零假设自助法规模（只报告，区间外会醒目标出）")
N_SELF = 200  # 200 条样本上每条样本自身自助分布的抽样次数


def self_bootstrap_quantile(
    y1: np.ndarray, x: np.ndarray, rng: np.random.Generator, n_draw: int, h: int = 12
) -> tuple[float, np.ndarray]:
    """返回真实 |t| 与自助 |t*| 数组。"""
    t_true = abs(nw_t_both(y1, x, h))
    n = len(y1)
    stats = np.empty(n_draw)
    for b in range(n_draw):
        idx = stationary_indices(n - 1, 12, rng)
        y_star, x_star = null_bootstrap_draw(y1, x, [], idx)
        stats[b] = abs(nw_t_both(y_star, x_star[:, 0], h))
    return t_true, stats


rng_d = np.random.default_rng(SEED)
y1_d, x_d = dgp(250, rng_d)
t_true, t_star = self_bootstrap_quantile(y1_d, x_d, rng_d, 500)
q95 = float(np.quantile(t_star, 0.95))
print(f"单条样本（n=250）：真实 |t| = {t_true:.3f}；500 组自助 |t*| 的 95% 分位 = {q95:.3f}")
print(f"  自助 |t*| 分位：50% {np.quantile(t_star, 0.5):.3f}  90% {np.quantile(t_star, 0.9):.3f}  "
      f"95% {q95:.3f}  99% {np.quantile(t_star, 0.99):.3f}")

rej, q95_each, t_each = [], [], []
for _ in range(N_SELF):
    y1_s, x_s = dgp(250, rng_d)
    t_s, draws = self_bootstrap_quantile(y1_s, x_s, rng_d, N_SELF)
    q = float(np.quantile(draws, 0.95))
    t_each.append(t_s)
    q95_each.append(q)
    rej.append(t_s > q)
q95_each = np.asarray(q95_each)
t_each = np.asarray(t_each)
rate_d = float(np.mean(rej))
print(
    f"{N_SELF} 条独立样本 × 每条 {N_SELF} 组自助：自助 95% 分位的中位数 {np.median(q95_each):.3f}"
    f"（四分位 {np.quantile(q95_each, 0.25):.3f}–{np.quantile(q95_each, 0.75):.3f}）；"
    f"真实 |t| 自身的 95% 分位 {np.quantile(t_each, 0.95):.3f}"
)
flag = "" if 0.02 <= rate_d <= 0.10 else "  <<<< 超出 [0.02, 0.10]，注意（只报告，不停止）"
print(f"真实 |t| 超过自身自助 95% 分位的比例 = {rate_d:.4f}{flag}")


# %% [markdown]
# ## E. 平稳自助法索引的平均块长

# %%
hdr("E. stationary_indices 平均块长（n=10000, mean_block=12，应在 11–13）")
rng_e = np.random.default_rng(SEED)
idx_e = stationary_indices(10000, 12, rng_e)
n_e = len(idx_e)
continues = (np.diff(idx_e) % n_e) == 1  # 索引恰好 +1（模 n）即仍在前一块里
n_segments = 1 + int((~continues).sum())
mean_len = n_e / n_segments
print(f"连续段数 {n_segments}，平均长度 {mean_len:.3f}")
mb = moving_block_indices(10000, 12, rng_e)
print(f"对照：moving_block_indices(n=10000, block=12) 长度 {len(mb)}，"
      f"逐块起点 {mb[0]}, {mb[12]}, {mb[24]} …（每 12 个必然跳一次）")
assert 11 <= mean_len <= 13, f"平均块长 {mean_len:.3f} 不在 11–13"
print("E 通过")


# %% [markdown]
# ## F. 真实数据：000985、V（只打印不判读）

# %%
hdr("F. 真实数据 IVX（000985.CSI，回归元 V，全样本从首月起）")
v = monthly[f"V|{MAIN}"].to_numpy()
y1_all = monthly[f"fwd1|{MAIN}"].to_numpy()
ok_ivx = ~(np.isnan(y1_all) | np.isnan(v))
assert np.array_equal(np.flatnonzero(ok_ivx), np.arange(ok_ivx.argmax(), ok_ivx.argmax() + ok_ivx.sum())), (
    "有效月份不连续，下面的「去 NaN 后直接切」会把不同月份拼在一起"
)
y1c, vc = y1_all[ok_ivx], v[ok_ivx]
first_valid = monthly.loc[ok_ivx, "period"].iloc[0]
rows = []
for h in HORIZONS:
    yh = monthly[f"fwd{h}|{MAIN}"].to_numpy()
    iv = ivx_wald(y1c, vc, h)
    ok_nw = ~(np.isnan(yh) | np.isnan(v))
    fit, n_nw = nw_ols(pd.Series(yh[ok_nw], name="y"), pd.DataFrame({"V": v[ok_nw]}), h)
    rows.append(
        {
            "h": h,
            "n_ivx": iv["n"],
            "coef": iv["coef"][0],
            "wald": iv["wald"],
            "p": iv["p"],
            "p_one_sided_pos": iv["p_one_sided_pos"],
            "t_nw": float(fit.tvalues["V"]),
            "n_nw": n_nw,
        }
    )
print(f"IVX 样本：{first_valid} 起 {len(y1c)} 个月（再去掉 y1 末一个未知月）；NW 样本随期限截尾")
print(pd.DataFrame(rows).round(4).to_string(index=False))
print("\n（只打印，不判读）")


# %%
hdr("完成")
print("A 通过；B 通过；C/D 只报告；E 通过；F 只打印。")
