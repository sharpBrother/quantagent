# %% [markdown]
# # A 股估值因子的统计稳健性（P1.1–P1.5）
#
# 方案固定于 `docs/research/erp-phase2-plan.md` 的 P1 一节（含末尾「补充」的评级规则），
# 判读阈值看结果前已写定，本脚本不改口径。数据全部来自上游 run
# `05cf3475b6354fa8be2c4d3f7bab942f` 的落盘 CSV，启动时逐个校验 sha256。
#
# - P1.1 Newey-West、IVX、零假设自助法、移动块自助置信区间、效应量
# - P1.2 训练起点网格
# - P1.3 经济显著性（均值-方差投资者，风险厌恶 3，仓位 0–1.5）
# - P1.4 多重检验（Holm/BH、Hansen SPA）
# - P1.5 逐条机器判定评级
#
# 只读 CSV、只写 `var/research/erp_valuation_robustness/<run_id>/`，落 run log，不写库。

# %%
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from arch.bootstrap import SPA
from erp_lib import (
    cash_accrual,
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
from statsmodels.stats.multitest import multipletests

from quantagent.platform.config import get_settings
from quantagent.platform.identity import digest_json, new_run_id
from quantagent.platform.runlog import RunLog, persist_run_log
from quantagent.platform.storage.paths import detect_repo_root, resolve_var_paths

if TYPE_CHECKING:
    from pathlib import Path

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 80)
pd.set_option("display.max_rows", 200)

started = time.monotonic()


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def hdr(title: str) -> None:
    print(f"\n{'=' * 96}\n{title}\n{'=' * 96}", flush=True)


def show(title: str, frame: pd.DataFrame, *, drop_index: bool = True) -> None:
    print(f"\n--- {title} ---", flush=True)
    print(frame.round(4).to_string(index=not drop_index), flush=True)


# %% [markdown]
# ## 上游固定输入与哈希校验
#
# 24 个 CSV 的 sha256 原样取自 `/tmp/p1_inputs.sha256`，任一不等即停。

# %%
UPSTREAM_RUN = "05cf3475b6354fa8be2c4d3f7bab942f"
UPSTREAM_SHA256 = {
    "monthly.csv": "4137e4b3e51dc71153e04ec69511e104c89f116d9232969ce327dbcebe01ced8",
    "daily.csv": "fbed0b9d3b865dc41bb93c8199229b71e7c1a1ed5d25233654abe9b7c0e6f3c6",
    "oos.csv": "53f54c85e56ec3fa3bf22789c82568c6e2d125ce0c9360466ea93123121bbe72",
    "strategy_U_us_5y_lag1.csv": "3b80c0e18297d9dde2f36e2195c9dc5dff6023fd251a7d3f2a76cea974f46d81",
    "strategy_V_cn_5y_lag1.csv": "93e88cb077b7dea0ff3cd35eff42c839eb96a07f9702226da31c6a6eafcbc875",
    "strategy_Max_us_cn_5y_lag1.csv": (
        "281c49998e6934825e2f569b8f8b751973199580ba41283b06324504fd05882f"
    ),
    "strategy_Ur_tips_5y_lag1.csv": "1299f9a68bbf23b4f839606c75e339a0996e0d16eb214ccce345ef75a380c111",
    "strategy_EY_5y_lag1.csv": "922aa9578909d363366fe54b97683ea15ce215a6faf1c110ca66a747052b0c7a",
    "strategy_p7_U_us_5y_lag1.csv": (
        "d5026b7132376619dadfa9b676e9f2fb520b65771de6e1947186c874bded9af0"
    ),
    "strategy_p7_V_cn_5y_lag1.csv": (
        "b35a5316bcd1d77e9fc3b4fce7011fba64ad679a3a5251ba33c1b3ffd736cb5f"
    ),
    "strategy_p7_Max_us_cn_5y_lag1.csv": (
        "fac6378aa8173b4183572b61b09f0fd6ec67b683b93ee5a9196354747877f4eb"
    ),
    "strategy_p7_Vn_cn_real_nbs_5y_lag1.csv": (
        "271e6b37e2a372e42efa417dece94b43085f37342ddb8839534b61113da23d31"
    ),
    "strategy_p7_Vm_mix_5y_lag1.csv": (
        "2669362da45a30cbd7809248b8902f6af00e1186a07dc5df6cf846e57018997b"
    ),
    "strategy_p7_Vcore_nonfood_5y_lag1.csv": (
        "79313cb844101a674fcad5be30910a8e69b0309ee21d8b84764b228daee46d6a"
    ),
    "strategy_p7_Vppi_5y_lag1.csv": "560a3f31a48a7d3edbd446e45aaafd770037317498ff38db809a215eeb2cae1f",
    "strategy_p7_EY_5y_lag1.csv": "d8f719bb0e86e4f7648a9a59e59dda3eae1183229dda33ab2d05efc5223efb8c",
    "strategy_real_U_us_5y_lag1.csv": (
        "7c0b73e0ad3fb61e6bc8e56f61d22229724810ace8e12fa78d563b3c084aae52"
    ),
    "strategy_real_U_de_5y_lag1.csv": (
        "8bc3e215aa391841e2300e2c69a99583f7c2ff2534258b99253ac91967556c9b"
    ),
    "strategy_real_U_jp_5y_lag1.csv": (
        "8429c556d74a69156ce5414b69816193477daa4c3ae6a85dd326d957d574de5a"
    ),
    "strategy_real_V_cn_5y_lag1.csv": (
        "dc96a9d5ffbf94adaeaf4adc87ea6c65026fbc3ac241adcc1ccceaee91a0e6e7"
    ),
    "strategy_real_Max_us_cn_5y_lag1.csv": (
        "966e47b206dc32d038eb6a11ad270350cfb882c98dadd565e24e8017036decf5"
    ),
    "strategy_real_Vr_cn_real_5y_lag1.csv": (
        "a53a2a5ad50e54456832f7844f8a4798da1e78290eaebfe3b85469fa8ff7be0e"
    ),
    "strategy_real_Vn_cn_real_nbs_5y_lag1.csv": (
        "1e7c29d52cfcd89cfb9e69634b60bbff3d0e5304a8421abee0443e6f8fb2e88d"
    ),
    "strategy_real_EY_5y_lag1.csv": "8b86d8163d383e67469627bdbd24b5b659ae511461a85f32f3f169e9764c0c4e",
}

settings = get_settings()
paths = resolve_var_paths(settings, repo_root=detect_repo_root())
# 上游 run 目录按平台路径解析（AGENTS §5.9 不写死绝对路径）；落在 /Volumes/QuantDB 下同一位置。
UP = paths.root / "research" / "erp_rate_anchor" / UPSTREAM_RUN


def sha256_of(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_upstream() -> None:
    bad = {
        name: (want, got)
        for name, want in UPSTREAM_SHA256.items()
        if (got := sha256_of(UP / name)) != want
    }
    if bad:
        raise RuntimeError(f"上游文件 sha256 不匹配，停止: {bad}")
    log(f"上游 sha256 校验通过：{len(UPSTREAM_SHA256)} 个文件，目录 {UP}")


hdr("上游输入校验")
verify_upstream()

# %% [markdown]
# ## 固定参数与样本
#
# 预测变量：`EY = ey`、`V`、`U`、`M = Mx`、`V+G`（两列，`G = r_us − r_cn`）。
# 月度远期收益：`y1 = fwd1`，`yh = forward_sum(y1, h)`；先断言与上游 `fwd{h}` 逐值一致。

# %%
MAIN = "000985.CSI"
INDICES = ("000985.CSI", "000300.SH", "000905.SH")
HORIZONS = (1, 3, 6, 12)
SAMPLE_START = "2004-12"  # monthly.csv 第一个 000985 估值有效月
OOS_START = "2012-12"
MIN_HISTORY = 36
TRAIN_STARTS = ("2005-01", "2006-01", "2007-01", "2008-01", "2009-01")
EXPLORATORY_START = "2007-01"  # 已被观察过，P1.2 里标 exploratory
SEED = 20261124
N_BOOT = 2000
BLOCK = 12  # 平稳/移动块自助法的平均块长（月）
CI_LEVELS = (0.025, 0.975)
P13_GAMMA = 3.0  # 风险厌恶，仓位 w = clip(预测超额/(gamma·var), 0, 1.5)
P13_W_MAX = 1.5
P13_VAR_WINDOW = 60  # 训练集最近 60 个月
P13_VAR_MIN = 24
SPA_BLOCKS = (63, 250)  # 交易日；63 是主口径，250 作敏感性
MODELS = {"EY": ("EY",), "V": ("V",), "U": ("U",), "V+G": ("V", "G"), "M": ("M",)}
GRADED = ("EY", "V", "U", "M")

PARAMS = {
    "upstream_run": UPSTREAM_RUN,
    "upstream_sha256_files": len(UPSTREAM_SHA256),
    "main_index": MAIN,
    "reported_indices": list(INDICES),
    "g_definition": "r_us - r_cn",
    "predictors": {k: list(v) for k, v in MODELS.items()},
    "horizons": list(HORIZONS),
    "sample_start": SAMPLE_START,
    "sample_rule": "各模型所有变量与 y1 都非 NaN 的最长连续区间",
    "oos_start": OOS_START,
    "min_history": MIN_HISTORY,
    "train_starts": list(TRAIN_STARTS),
    "exploratory_start": EXPLORATORY_START,
    "seed": SEED,
    "n_boot": N_BOOT,
    "block": BLOCK,
    "nw_lag_rule": "max(h, 1)",
    "ci_levels": list(CI_LEVELS),
    "effect_1sd": "coef * std(X_col, ddof=1)，h 期百分点",
    "p13": {
        "horizon": 1,
        "train_start": "2005-01",
        "gamma": P13_GAMMA,
        "w_cap": [0.0, P13_W_MAX],
        "var_window": P13_VAR_WINDOW,
        "var_min": P13_VAR_MIN,
        "cer": "12 * (mean(rp) - gamma/2 * var(rp) / 100)，rp 为百分点；w = clip(100 * (f - cash) / (gamma * var), 0, 1.5)",
    },
    "spa": {
        "loss": "-ret（同一现金腿，现金抵消）",
        "blocks": list(SPA_BLOCKS),
        "bootstrap": "stationary",
        "studentize": True,
        "reps": N_BOOT,
    },
    "float_precision": "round_trip",
}

input_digest = digest_json({"params": PARAMS, "upstream": UPSTREAM_SHA256})
log(f"input_digest = {input_digest}")

# %%
hdr("读取上游落盘")
monthly = pd.read_csv(UP / "monthly.csv", float_precision="round_trip")
daily = pd.read_csv(UP / "daily.csv", index_col=0, parse_dates=True, float_precision="round_trip")
period = monthly["period"].to_numpy()
G = (monthly["r_us"] - monthly["r_cn"]).to_numpy()
log(f"monthly {monthly.shape}，daily {daily.shape}，月份 {period[0]}..{period[-1]}")


def var_map(code: str) -> dict[str, np.ndarray]:
    """该指数的五个预测变量原值（M 用上游的 Mx 列）。"""
    return {
        "EY": monthly[f"ey|{code}"].to_numpy(),
        "V": monthly[f"V|{code}"].to_numpy(),
        "U": monthly[f"U|{code}"].to_numpy(),
        "M": monthly[f"Mx|{code}"].to_numpy(),
        "G": G,
    }


def design(vm: dict[str, np.ndarray], cols: tuple[str, ...]) -> np.ndarray:
    return np.column_stack([vm[c] for c in cols])


def longest_valid_run(arrays: list[np.ndarray], first: int) -> tuple[int, int]:
    """``first`` 之后各数组都非 NaN 的最长连续区间的起止位置（含）。"""
    ok = ~np.isnan(np.column_stack(arrays)).any(axis=1)
    ok[:first] = False
    best = (0, -1)
    begin = None
    for i, flag in enumerate(ok):
        if flag and begin is None:
            begin = i
        elif not flag and begin is not None:
            if i - 1 - begin > best[1] - best[0]:
                best = (begin, i - 1)
            begin = None
    if begin is not None and len(ok) - 1 - begin > best[1] - best[0]:
        best = (begin, len(ok) - 1)
    if best[1] < best[0]:
        raise RuntimeError("没有可用样本，停止")
    return best


# 断言 1：forward_sum 与上游 fwd{h} 一致（数值与 NaN 位置）
hdr("断言 1：forward_sum(y1, h) 与 monthly.csv 的 fwd{h} 一致")
for code in INDICES:
    y1_full = monthly[f"fwd1|{code}"].to_numpy()
    for h in HORIZONS:
        yh = forward_sum(y1_full, h)
        ref = monthly[f"fwd{h}|{code}"].to_numpy()
        if not np.array_equal(np.isnan(yh), np.isnan(ref)):
            raise RuntimeError(f"{code} h={h} 的 NaN 位置不一致，停止")
        both = ~np.isnan(yh)
        diff = float(np.max(np.abs(yh[both] - ref[both]))) if both.any() else 0.0
        if diff >= 1e-9:
            raise RuntimeError(f"{code} h={h} 的 forward_sum 与 fwd 差 {diff:.3e}，停止")
        print(f"  {code} h={h:2d}: 非 NaN {both.sum():3d} 个，最大绝对差 {diff:.3e}", flush=True)
print("断言 1 通过（阈值 1e-9，NaN 位置一致）", flush=True)

# 样本区间：各指数取自已最长的连续有效区间
sample_span: dict[str, tuple[int, int]] = {}
start_pos_of = int(np.flatnonzero(period == SAMPLE_START)[0])
for code in INDICES:
    vm = var_map(code)
    arrays = [monthly[f"fwd1|{code}"].to_numpy(), *[vm[c] for c in vm]]
    sample_span[code] = longest_valid_run(arrays, start_pos_of)
hdr("样本区间（各模型所有变量与 y1 都非 NaN 的最长连续段）")
for code in INDICES:
    a, b = sample_span[code]
    print(f"  {code}: {period[a]} .. {period[b]}，{b - a + 1} 个月", flush=True)

# %% [markdown]
# ## P1.1 推断
#
# Newey-West 是基准；IVX 报告单变量 Wald（V+G 报联合，并对 G 单独再检）；零假设自助法只跑主口径；
# 系数置信区间用移动块自助法。
#
# 自助法的随机数：`SeedSequence(SEED).spawn(len(MODELS))` 给每个模型一条独立子流，
# 每条再 `.spawn(2)` 分成零假设自助与置信区间两条，互不干扰、与模型顺序无关地可复现。


# %%
def nw_hac(y: np.ndarray, x: np.ndarray, h: int) -> tuple[np.ndarray, np.ndarray]:
    """``y ~ 1 + x`` 的 Newey-West 系数与 t 值（Bartlett 权重，滞后 max(h,1)，无小样本修正）。

    与 `erp_lib.nw_ols`（statsmodels ``cov_type="HAC"``）逐值一致（脚本内先断言到 1e-8）：
    自助法里要重抽 2000 次、每次 4 个期限，statsmodels 的固定开销不可接受。
    返回的 ``coef``/``t`` 第 0 位是截距。
    """
    matrix = np.column_stack([np.ones(y.shape[0]), x])
    xtx = matrix.T @ matrix
    coef = np.linalg.solve(xtx, matrix.T @ y)
    resid = y - matrix @ coef
    xe = matrix * resid[:, None]
    sigma = xe.T @ xe
    lags = max(int(h), 1)
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        cross = xe[lag:].T @ xe[:-lag]
        sigma += weight * (cross + cross.T)
    cov = np.linalg.solve(xtx, sigma) @ np.linalg.inv(xtx)
    return coef, coef / np.sqrt(np.diag(cov))


hdr("断言 2：numpy HAC 与 erp_lib.nw_ols 的系数与 t 值一致")
worst_coef = 0.0
worst_t = 0.0
for code in INDICES:
    vm = var_map(code)
    y1_full = monthly[f"fwd1|{code}"].to_numpy()
    for _model, cols in MODELS.items():
        x_full = design(vm, cols)
        for h in HORIZONS:
            yh = forward_sum(y1_full, h)
            ok = ~np.isnan(yh) & ~np.isnan(x_full).any(axis=1)
            fit, n_fit = nw_ols(
                pd.Series(yh[ok], name="y"), pd.DataFrame(x_full[ok], columns=list(cols)), h
            )
            coef, tvals = nw_hac(yh[ok], x_full[ok], h)
            for j, var in enumerate(cols):
                worst_coef = max(worst_coef, abs(coef[j + 1] - float(fit.params[var])))
                worst_t = max(worst_t, abs(tvals[j + 1] - float(fit.tvalues[var])))
print(f"  最大系数差 {worst_coef:.3e}，最大 t 差 {worst_t:.3e}（阈值 1e-8）", flush=True)
if worst_coef >= 1e-8 or worst_t >= 1e-8:
    raise RuntimeError("numpy HAC 与 nw_ols 不一致，停止")
print("断言 2 通过", flush=True)

# %%
hdr("P1.1 推断（NW / IVX / 零假设自助 / 移动块 CI / 效应量）")
t_p11 = time.monotonic()
p11_rows: dict[tuple[str, str, int, str], dict[str, object]] = {}
p11_order: list[tuple[str, str, int, str]] = []


def p11_row(index: str, model: str, h: int, var: str) -> dict[str, object]:
    key = (index, model, int(h), var)
    if key not in p11_rows:
        p11_rows[key] = {"index": index, "model": model, "h": int(h), "var": var}
        p11_order.append(key)
    return p11_rows[key]


# 第一步：全样本 NW（三个指数）+ IVX（三个指数，各取自己的最长连续段）
for code in INDICES:
    vm = var_map(code)
    y1_full = monthly[f"fwd1|{code}"].to_numpy()
    a, b = sample_span[code]
    y1c = y1_full[a : b + 1]
    vmc = {k: v[a : b + 1] for k, v in vm.items()}
    for model, cols in MODELS.items():
        x_full = design(vm, cols)
        xc = design(vmc, cols)
        for h in HORIZONS:
            yh = forward_sum(y1_full, h)
            ok = ~np.isnan(yh) & ~np.isnan(x_full).any(axis=1)
            fit, n_fit = nw_ols(
                pd.Series(yh[ok], name="y"), pd.DataFrame(x_full[ok], columns=list(cols)), h
            )
            for j, var in enumerate(cols):
                row = p11_row(code, model, h, var)
                row["coef"] = float(fit.params[var])
                row["t_nw"] = float(fit.tvalues[var])
                row["n"] = int(n_fit)
                row["effect_1sd"] = row["coef"] * float(np.std(x_full[ok][:, j], ddof=1))
            ivx = ivx_wald(y1c, xc, h)
            if len(cols) == 1:
                row = p11_row(code, model, h, cols[0])
                row["ivx_kind"] = "single"
                row["ivx_coef"] = float(ivx["coef"][0])
                row["ivx_wald"] = ivx["wald"]
                row["ivx_p"] = ivx["p"]
                row["ivx_p_pos"] = ivx["p_one_sided_pos"]
                row["ivx_n"] = ivx["n"]
            else:
                joint = p11_row(code, model, h, cols[0])
                joint["ivx_kind"] = "joint"
                joint["ivx_wald"] = ivx["wald"]
                joint["ivx_p"] = ivx["p"]
                joint["ivx_n"] = ivx["n"]
                only_g = ivx_wald(y1c, xc, h, cols=[1])
                row_g = p11_row(code, model, h, cols[1])
                row_g["ivx_kind"] = "G_only"
                row_g["ivx_coef"] = float(only_g["coef"][1])
                row_g["ivx_wald"] = only_g["wald"]
                row_g["ivx_p"] = only_g["p"]
                row_g["ivx_p_pos"] = only_g["p_one_sided_pos"]
                row_g["ivx_n"] = only_g["n"]
log(f"NW 与 IVX 完成，耗时 {time.monotonic() - t_p11:.1f}s")

# 第二步：主口径的零假设自助法 + 移动块自助置信区间
vm_main = var_map(MAIN)
a_main, b_main = sample_span[MAIN]
y1_main_c = monthly[f"fwd1|{MAIN}"].to_numpy()[a_main : b_main + 1]
oos_rel = int(np.flatnonzero(period == OOS_START)[0]) - a_main
if oos_rel < 0:
    raise RuntimeError(f"OOS_START {OOS_START} 早于样本起点，停止")
n_main = len(y1_main_c)
model_rngs = np.random.SeedSequence(SEED).spawn(len(MODELS))
log(
    f"零假设自助：N_BOOT={N_BOOT}，BLOCK={BLOCK}，样本 {n_main} 个月，"
    f"oos_start 位置 {oos_rel}（{OOS_START}）；种子 = SeedSequence({SEED}).spawn(5) 再各 spawn(2)"
)

for j, (model, cols) in enumerate(MODELS.items()):
    xc = design(vm_main, cols)[a_main : b_main + 1]
    # 单变量模型的零假设就是「无预测力」（keep_cols=[]）；V+G 只检验 G（保留 V）
    keep_cols = [] if len(cols) == 1 else [0]
    seed_null, seed_ci = model_rngs[j].spawn(2)
    rng_null = np.random.default_rng(seed_null)
    rng_ci = np.random.default_rng(seed_ci)

    real = {}
    for h in HORIZONS:
        yh = forward_sum(y1_main_c, h)
        ok = ~np.isnan(yh)
        _, t_real = nw_hac(yh[ok], xc[ok], h)
        fc = oos_expanding(
            yh, xc, h, train_start=0, oos_start=oos_rel, min_history=MIN_HISTORY
        ).dropna()
        real[h] = {
            "t": t_real[1:],
            "r2": r2_os(fc["y"], fc["model"], fc["M0"]),
            "cw": clark_west_np(fc["y"], fc["M0"], fc["model"], h)[0],
        }

    k = len(cols)
    boot_t = {h: np.empty((N_BOOT, k)) for h in HORIZONS}
    boot_r2 = {h: np.empty(N_BOOT) for h in HORIZONS}
    boot_cw = {h: np.empty(N_BOOT) for h in HORIZONS}
    t_model = time.monotonic()
    for b in range(N_BOOT):
        idx = stationary_indices(n_main - 1, BLOCK, rng_null)
        y_star, x_star = null_bootstrap_draw(y1_main_c, xc, keep_cols, idx)
        for h in HORIZONS:
            yh_star = forward_sum(y_star, h)
            ok = ~np.isnan(yh_star)
            _, t_star = nw_hac(yh_star[ok], x_star[ok], h)
            boot_t[h][b] = t_star[1:]
            fc = oos_expanding(
                yh_star, x_star, h, train_start=0, oos_start=oos_rel, min_history=MIN_HISTORY
            ).dropna()
            if fc.empty:
                raise RuntimeError(f"{model} h={h} 的自助样本没有样本外月份，停止")
            boot_r2[h][b] = r2_os(fc["y"], fc["model"], fc["M0"])
            boot_cw[h][b] = clark_west_np(fc["y"], fc["M0"], fc["model"], h)[0]
    log(f"  {model}: 零假设自助 {N_BOOT} 次耗时 {time.monotonic() - t_model:.1f}s")

    slopes = {}
    for h in HORIZONS:
        yh = forward_sum(y1_main_c, h)
        ok = ~np.isnan(yh)
        y_use, x_use = yh[ok], xc[ok]
        draws = np.empty((N_BOOT, k))
        for b in range(N_BOOT):
            idx = moving_block_indices(len(y_use), BLOCK, rng_ci)
            matrix = np.column_stack([np.ones(len(idx)), x_use[idx]])
            draws[b] = np.linalg.lstsq(matrix, y_use[idx], rcond=None)[0][1:]
        slopes[h] = np.quantile(draws, CI_LEVELS, axis=0)

    for h in HORIZONS:
        for jj, var in enumerate(cols):
            row = p11_row(MAIN, model, h, var)
            row["ci_lo"] = float(slopes[h][0, jj])
            row["ci_hi"] = float(slopes[h][1, jj])
            if jj == 0:
                # 模型层面的样本外指标放在第一个变量那一行，避免同一组数字重复两遍
                row["r2_os"] = real[h]["r2"]
                row["cw_t"] = real[h]["cw"]
                row["p_boot_r2"] = float(np.mean(boot_r2[h] >= real[h]["r2"]))
                row["p_boot_cw"] = float(np.mean(boot_cw[h] >= real[h]["cw"]))
            t_real = real[h]["t"][jj]
            t_star = boot_t[h][:, jj]
            if k == 1:
                row["p_boot_t_one_sided"] = float(np.mean(t_star >= t_real))
            else:
                row["p_boot_t_two_sided"] = float(np.mean(np.abs(t_star) >= abs(t_real)))
log(f"P1.1 全部完成，耗时 {time.monotonic() - t_p11:.1f}s")

p11 = pd.DataFrame([p11_rows[key] for key in p11_order])
p11_cols = [
    "index",
    "model",
    "h",
    "var",
    "coef",
    "t_nw",
    "n",
    "effect_1sd",
    "ci_lo",
    "ci_hi",
    "ivx_kind",
    "ivx_coef",
    "ivx_wald",
    "ivx_p",
    "ivx_p_pos",
    "ivx_n",
    "r2_os",
    "cw_t",
    "p_boot_t_one_sided",
    "p_boot_t_two_sided",
    "p_boot_r2",
    "p_boot_cw",
]
p11 = p11[p11_cols]
show("P1.1 p11_inference（000985.CSI 主口径）", p11[p11["index"] == MAIN])
show(
    "P1.1 另两个指数的 IVX p（两列期限并用；只报告，不判读）",
    p11[p11["index"] != MAIN]
    .pivot_table(index=["index", "model", "var", "ivx_kind"], columns="h", values="ivx_p")
    .reset_index(),
)

# %% [markdown]
# ## P1.2 训练起点网格（仅 000985）
#
# 评估月份先取交集再统一过滤：同一期限下五个起点、五个模型用完全相同的月份集合。


# %%
hdr("P1.2 训练起点网格")
t_p12 = time.monotonic()
vm_s = {k: v[a_main : b_main + 1] for k, v in vm_main.items()}
y1_s = y1_main_c
pos_of_period = {p: i for i, p in enumerate(period)}
train_pos = {s: pos_of_period[s] - a_main for s in TRAIN_STARTS}
all_x_s = np.column_stack([design(vm_s, cols) for cols in MODELS.values()])

p12_rows: list[dict[str, object]] = []
eval_months_by_h: dict[int, list[int]] = {}
for h in HORIZONS:
    yh = forward_sum(y1_s, h)
    base = np.zeros(n_main, dtype=bool)
    base[oos_rel:] = True
    base &= ~np.isnan(yh) & ~np.isnan(all_x_s).any(axis=1)
    per_start: dict[str, dict[str, pd.DataFrame]] = {}
    common = set(np.flatnonzero(base).tolist())
    for start in TRAIN_STARTS:
        per_start[start] = {}
        for model, cols in MODELS.items():
            fc = oos_expanding(
                yh,
                design(vm_s, cols),
                h,
                train_start=train_pos[start],
                oos_start=oos_rel,
                min_history=MIN_HISTORY,
            )
            per_start[start][model] = fc
            common &= set(fc.index.tolist())
    months = sorted(common)
    if not months:
        raise RuntimeError(f"h={h} 的评估月份集合为空，停止")
    eval_months_by_h[h] = months
    print(
        f"\nh={h:2d}: 评估 {len(months)} 个月，{period[a_main + months[0]]} .. "
        f"{period[a_main + months[-1]]}（取交集前 {int(base.sum())} 个月）",
        flush=True,
    )
    for start in TRAIN_STARTS:
        for model in MODELS:
            fc = per_start[start][model].loc[months]
            if fc["model"].isna().any():
                raise RuntimeError(f"S={start} {model} h={h} 评估月里有 NaN 预测，停止")
            y_use = fc["y"].to_numpy()
            f_use = fc["model"].to_numpy()
            f0_use = fc["M0"].to_numpy()
            cw_t, cw_p = clark_west_np(y_use, f0_use, f_use, h)
            p12_rows.append(
                {
                    "S": start,
                    "h": h,
                    "model": model,
                    "n": len(fc),
                    "r2_os": r2_os(y_use, f_use, f0_use),
                    "cw_t": cw_t,
                    "cw_p": cw_p,
                    "msfe_model": float(np.mean((y_use - f_use) ** 2)),
                    "msfe_m0": float(np.mean((y_use - f0_use) ** 2)),
                    "slope_pos_share": float(np.mean(fc["slope"].to_numpy() > 0)),
                    "slope_last": float(fc["slope"].to_numpy()[-1]),
                    "exploratory": start == EXPLORATORY_START,
                }
            )
p12 = pd.DataFrame(p12_rows)
log(f"P1.2 完成，耗时 {time.monotonic() - t_p12:.1f}s")
show("P1.2 p12_grid", p12)

# %% [markdown]
# ## P1.3 经济显著性（h=1，训练起点 2005-01）
#
# 月度现金收益：`cash_accrual` 给日现金收益，再按 `fwd1` 的同一个持有期
# `(entry_i, entry_{i+1}]` 累加。先断言用 `ret|000985.CSI` 按该区间算出的收益与 `fwd1`
# 一致到 1e-9，确认区间定义没跑偏。
#
# 单位：`ex`、`f − cash_m`、`rp` 都是百分点/月，`var` 是百分点²，`CER` 是百分点/年。

# %%
hdr("断言 3：日频 ret 按 (entry_i, entry_{i+1}] 累加与 fwd1 一致")
daily_index = daily.index
log_ret_main = np.log1p(daily[f"ret|{MAIN}"])
cash_daily = cash_accrual(daily["r_cn"])
signal_dt = pd.to_datetime(monthly["signal_dt"]).to_numpy()
next_pos = daily_index.searchsorted(signal_dt, side="right")
entry = np.full(len(monthly), np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
has_entry = next_pos < len(daily_index)
entry[has_entry] = daily_index.to_numpy()[np.clip(next_pos, 0, len(daily_index) - 1)][has_entry]

fwd1_ref = monthly[f"fwd1|{MAIN}"].to_numpy()
fwd1_check = np.full(len(monthly), np.nan)
cash_m_full = np.full(len(monthly), np.nan)
for i in range(len(monthly) - 1):
    left, right = entry[i], entry[i + 1]
    if np.isnat(left) or np.isnat(right):
        continue
    window = log_ret_main.loc[(daily_index > left) & (daily_index <= right)]
    if not window.empty and not window.isna().any():
        fwd1_check[i] = float(window.sum() * 100.0)
    cash_window = cash_daily.loc[(daily_index > left) & (daily_index <= right)]
    if not cash_window.empty and not cash_window.isna().any():
        cash_m_full[i] = float(np.log1p(cash_window).sum() * 100.0)
if not np.array_equal(np.isnan(fwd1_check), np.isnan(fwd1_ref)):
    raise RuntimeError("按持有期累加的 NaN 位置与 fwd1 不一致，停止")
both_fwd = ~np.isnan(fwd1_check)
diff_fwd = float(np.max(np.abs(fwd1_check[both_fwd] - fwd1_ref[both_fwd])))
print(f"  非 NaN {both_fwd.sum()} 个月，最大绝对差 {diff_fwd:.3e}（阈值 1e-9）", flush=True)
if diff_fwd >= 1e-9:
    raise RuntimeError(f"持有期定义与 fwd1 不一致（{diff_fwd:.3e}），停止")
print("断言 3 通过", flush=True)

# %%
hdr("P1.3 经济显著性（h=1，S=2005-01）")
t_p13 = time.monotonic()
# 评估月份直接沿用 P1.2 的交集（五个起点、五个模型完全相同的那一批月）
eval_months = eval_months_by_h[1]
yh1 = forward_sum(y1_s, 1)
train_start_p13 = train_pos["2005-01"]

ex_full = fwd1_ref - cash_m_full
ex_slice = ex_full[a_main : b_main + 1]
cash_slice = cash_m_full[a_main : b_main + 1]

f13: dict[str, pd.DataFrame] = {}
for model in ("M0", *MODELS):
    cols = MODELS.get(model)
    if model == "M0":
        base_fc = oos_expanding(
            yh1,
            design(vm_s, ("EY",)),
            1,
            train_start=train_start_p13,
            oos_start=oos_rel,
            min_history=MIN_HISTORY,
        )
        f13[model] = base_fc[["M0"]].rename(columns={"M0": "f"}).loc[eval_months]
    else:
        f13[model] = (
            oos_expanding(
                yh1,
                design(vm_s, cols),
                1,
                train_start=train_start_p13,
                oos_start=oos_rel,
                min_history=MIN_HISTORY,
            )[["model"]]
            .rename(columns={"model": "f"})
            .loc[eval_months]
        )

p13_rows: list[dict[str, object]] = []
skipped = 0
for model, frame in f13.items():
    rp_list: list[float] = []
    w_list: list[float] = []
    for i in eval_months:
        hist = np.arange(train_start_p13, i - 1)  # h=1: 训练月上限 i−h−1 = i−2
        hist = hist[~np.isnan(yh1[hist]) & ~np.isnan(ex_slice[hist])]
        if len(hist) < P13_VAR_MIN:
            if model == "M0":
                skipped += 1
            continue
        window = hist[-P13_VAR_WINDOW:]
        var_ex = float(np.var(ex_slice[window], ddof=1))
        # ex、f 是百分点，var_ex 是百分点平方；均值-方差权重要用小数口径：
        # (f/100) / (gamma * var/100²) = 100 * f / (gamma * var)
        raw = 100.0 * (float(frame.loc[i, "f"]) - cash_slice[i]) / (P13_GAMMA * var_ex)
        w = float(np.clip(raw, 0.0, P13_W_MAX))
        w_list.append(w)
        rp_list.append(w * ex_slice[i])
    rp = np.asarray(rp_list)
    # rp 是百分点：CER(小数) = mean(rp/100) - gamma/2 * var(rp/100)，换回百分点即下式
    cer = float(12.0 * (rp.mean() - 0.5 * P13_GAMMA * np.var(rp, ddof=1) / 100.0))
    p13_rows.append({"model": model, "n": len(rp), "cer": cer, "mean_w": float(np.mean(w_list))})
p13 = pd.DataFrame(p13_rows)
cer_m0 = float(p13.loc[p13["model"] == "M0", "cer"].iloc[0])
p13["cer_gain_vs_m0"] = p13["cer"] - cer_m0
p13 = p13[["model", "n", "cer", "cer_gain_vs_m0", "mean_w"]]
log(
    f"P1.3 完成，耗时 {time.monotonic() - t_p13:.1f}s；训练期不足 {P13_VAR_MIN} 个月而跳过的评估月 {skipped} 个"
)
show("P1.3 p13_cer（百分点/年；ex、var 单位见上）", p13)

# %% [markdown]
# ## P1.4 多重检验
#
# 预测族：训练起点 2005-01 的 5 模型 × 4 期限 Clark-West p（相对 M0），Holm 与 BH。
# 策略族：Hansen SPA，损失 = −日收益（同一现金腿，现金抵消），平稳自助法，b = 63 / 250。

# %%
hdr("P1.4 多重检验：Holm / BH（S=2005-01，CW 相对 M0）")
p14_src = p12[p12["S"] == "2005-01"].sort_values(["model", "h"]).reset_index(drop=True)
p_holm = multipletests(p14_src["cw_p"].to_numpy(), method="holm")[1]
p_bh = multipletests(p14_src["cw_p"].to_numpy(), method="fdr_bh")[1]
p14_holm = p14_src[["model", "h", "n", "cw_t", "cw_p"]].copy()
p14_holm["p_holm"] = p_holm
p14_holm["p_fdr_bh"] = p_bh
show("P1.4 p14_holm（20 个检验）", p14_holm)

# %%
hdr("P1.4 多重检验：Hansen SPA")
t_spa = time.monotonic()
SPA_GROUPS = {
    "g1": {
        "U_us": "strategy_U_us_5y_lag1.csv",
        "V_cn": "strategy_V_cn_5y_lag1.csv",
        "Max_us_cn": "strategy_Max_us_cn_5y_lag1.csv",
        "Ur_tips": "strategy_Ur_tips_5y_lag1.csv",
        "EY": "strategy_EY_5y_lag1.csv",
    },
    "g2": {
        "U_us": "strategy_p7_U_us_5y_lag1.csv",
        "V_cn": "strategy_p7_V_cn_5y_lag1.csv",
        "Max_us_cn": "strategy_p7_Max_us_cn_5y_lag1.csv",
        "Vn_cn_real_nbs": "strategy_p7_Vn_cn_real_nbs_5y_lag1.csv",
        "Vm_mix": "strategy_p7_Vm_mix_5y_lag1.csv",
        "Vcore_nonfood": "strategy_p7_Vcore_nonfood_5y_lag1.csv",
        "Vppi": "strategy_p7_Vppi_5y_lag1.csv",
        "EY": "strategy_p7_EY_5y_lag1.csv",
    },
    "g3": {
        "U_us": "strategy_real_U_us_5y_lag1.csv",
        "U_de": "strategy_real_U_de_5y_lag1.csv",
        "U_jp": "strategy_real_U_jp_5y_lag1.csv",
        "V_cn": "strategy_real_V_cn_5y_lag1.csv",
        "Max_us_cn": "strategy_real_Max_us_cn_5y_lag1.csv",
        "Vr_cn_real": "strategy_real_Vr_cn_real_5y_lag1.csv",
        "Vn_cn_real_nbs": "strategy_real_Vn_cn_real_nbs_5y_lag1.csv",
        "EY": "strategy_real_EY_5y_lag1.csv",
    },
}

spa_rows: list[dict[str, object]] = []
for group, files in SPA_GROUPS.items():
    rets = {
        name: pd.read_csv(UP / fname, index_col=0, parse_dates=True, float_precision="round_trip")[
            "ret"
        ]
        for name, fname in files.items()
    }
    frame = pd.DataFrame(rets).dropna()
    print(
        f"\n{group}: 共同非 NaN 交易日 {len(frame)} 个，{frame.index[0].date()} .. "
        f"{frame.index[-1].date()}",
        flush=True,
    )
    for benchmark in ("V_cn", "EY"):
        candidates = [c for c in frame.columns if c != benchmark]
        bench_loss = -frame[benchmark].to_numpy()
        model_losses = -frame[candidates].to_numpy()
        mean_loss = model_losses.mean(axis=0)
        best_j = int(np.argmin(mean_loss))
        for block in SPA_BLOCKS:
            spa = SPA(
                bench_loss,
                model_losses,
                block_size=block,
                reps=N_BOOT,
                bootstrap="stationary",
                studentize=True,
                seed=SEED,
            )
            spa.compute()
            pvals = spa.pvalues
            spa_rows.append(
                {
                    "group": group,
                    "benchmark": benchmark,
                    "block": block,
                    "n_days": len(frame),
                    "n_models": len(candidates),
                    "p_lower": float(pvals["lower"]),
                    "p_consistent": float(pvals["consistent"]),
                    "p_upper": float(pvals["upper"]),
                    "best_model": candidates[best_j],
                    "best_mean_diff_bp": float(bench_loss.mean() - mean_loss[best_j]) * 1e4,
                }
            )
p14_spa = pd.DataFrame(spa_rows)
log(f"SPA 完成，耗时 {time.monotonic() - t_spa:.1f}s")
show("P1.4 p14_spa", p14_spa)

# %% [markdown]
# ## P1.5 评级（按计划判读标准与「补充」逐条机器判定）
#
# 1. 训练起点 2005-01 下 Holm 调整后 CW p < 0.05 的期限至少 2 个；
# 2. 这些期限上，5 个训练起点里至少 4 个 R²_OS > 0；
# 3. 同期限的 IVX 单边 p < 0.05 或零假设自助单边 p < 0.05。
#
# 三条都满足为第 3 类（已观察样本）；否则满足第 1 条或第 3 条在 4 个期限中至少 2 个成立为
# 第 2 类；其余第 5 类。

# %%
hdr("P1.5 评级")
p11_main = p11[p11["index"] == MAIN].set_index(["model", "h", "var"])
p12_idx = p12.set_index(["S", "model", "h"])
p_holm_idx = p14_holm.set_index(["model", "h"])["p_holm"]


def as_list(items: list[int]) -> str:
    return ",".join(str(int(v)) for v in items)


grade_rows: list[dict[str, object]] = []
for model in GRADED:
    c1_h = [h for h in HORIZONS if float(p_holm_idx.loc[(model, h)]) < 0.05]
    c1 = len(c1_h) >= 2
    c2 = bool(c1_h) and all(
        sum(float(p12_idx.loc[(s, model, h), "r2_os"]) > 0 for s in TRAIN_STARTS) >= 4 for h in c1_h
    )
    c3_h = []
    for h in HORIZONS:
        ivx_p = float(p11_main.loc[(model, h, model), "ivx_p_pos"])
        boot_p = float(p11_main.loc[(model, h, model), "p_boot_t_one_sided"])
        if ivx_p < 0.05 or boot_p < 0.05:
            c3_h.append(h)
    c3_on_c1 = all(h in c3_h for h in c1_h)
    if c1 and c2 and c3_on_c1:
        grade = "3（已观察样本）"
    elif c1 or len(c3_h) >= 2:
        grade = "2"
    else:
        grade = "5"
    grade_rows.append(
        {
            "model": model,
            "c1_horizons": as_list(c1_h),
            "c1": c1,
            "c2": c2,
            "c3_horizons": as_list(c3_h),
            "c3_on_c1": c3_on_c1,
            "grade": grade,
        }
    )
p15 = pd.DataFrame(grade_rows)
show("P1.5 p15_grade", p15)

# V+G 的 G：只报告，不评级
g_rows = []
for h in HORIZONS:
    row_vg_joint = p11_main.loc[("V+G", h, "V")]
    row_g = p11_main.loc[("V+G", h, "G")]
    g_rows.append(
        {
            "h": h,
            "t_nw": float(row_g["t_nw"]),
            "ivx_p_g": float(row_g["ivx_p"]),
            "ivx_p_joint": float(row_vg_joint["ivx_p"]),
            "p_boot_t_two_sided": float(row_g["p_boot_t_two_sided"]),
            "coef": float(row_g["coef"]),
            "effect_1sd": float(row_g["effect_1sd"]),
        }
    )
p15_g = pd.DataFrame(g_rows)
show("P1.5 V+G 中的 G（只报告，不评级；每个期限一行）", p15_g)

# %% [markdown]
# ## 落盘：结果表、summary.json、run log

# %%
results = {
    "p11_inference": p11.reset_index(drop=True),
    "p12_grid": p12.reset_index(drop=True),
    "p13_cer": p13.reset_index(drop=True),
    "p14_holm": p14_holm.reset_index(drop=True),
    "p14_spa": p14_spa.reset_index(drop=True),
    "p15_grade": p15.reset_index(drop=True),
    "p15_vg_g": p15_g.reset_index(drop=True),
}
output_digest = digest_json(
    {name: json.loads(frame.to_json(orient="records")) for name, frame in results.items()}
)

upstream_summary = json.loads((UP / "summary.json").read_text(encoding="utf-8"))
pit_report = json.loads(json.dumps(upstream_summary["pit_report"]))
pit_report["notes"] = [
    *pit_report["notes"],
    f"P1 使用上游 run {UPSTREAM_RUN} 的月度面板与策略日收益，按 sha256 校验。",
]

run_id = new_run_id()
out_dir = paths.root / "research" / "erp_valuation_robustness" / run_id
out_dir.mkdir(parents=True, exist_ok=False)
for name, frame in results.items():
    frame.to_csv(out_dir / f"{name}.csv", index=False)
summary = {
    "params": PARAMS,
    "upstream_sha256": UPSTREAM_SHA256,
    "pit_report": pit_report,
    "input_digest": input_digest,
    "output_digest": output_digest,
    "research_only": True,
    "no_database_write": True,
    "production_qualified": False,
}
(out_dir / "summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
)
row_count = int(sum(len(frame) for frame in results.values()))
run_log_path = persist_run_log(
    RunLog(
        run_id=run_id,
        action="research.erp_valuation_robustness",
        status="success",
        finished_at=datetime.now(UTC),
        elapsed_ms=int((time.monotonic() - started) * 1000),
        input_digest=input_digest,
        output_digest=output_digest,
        row_count=row_count,
        dml_count=0,
    ),
    paths,
)
hdr("落盘")
log(f"输出目录 {out_dir}")
log(f"run log {run_log_path}")
log(f"input_digest  {input_digest}")
log(f"output_digest {output_digest}")
log(f"总行数 {row_count}，总耗时 {time.monotonic() - started:.1f}s")
sys.stdout.flush()
