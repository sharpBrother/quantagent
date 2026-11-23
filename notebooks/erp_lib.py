"""研究线 erp-rate-anchor 的公共计算：分位、仓位规则、绩效与样本外统计。

函数从 `notebooks/2026-11-23-erp-rate-anchor.py` 原样搬出，行为由那次运行的输出约束
（run ``05cf3475b6354fa8be2c4d3f7bab942f``）：抽出后新旧结果必须逐字节一致。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import chi2, norm

if TYPE_CHECKING:
    from collections.abc import Sequence

# 年化用的交易日数，与原脚本一致
TRADING_DAYS = 244


def asof_lookup(series: pd.Series, cutoffs: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    pos = series.index.searchsorted(cutoffs, side="right") - 1
    vals = np.where(pos >= 0, series.to_numpy()[np.clip(pos, 0, None)], np.nan)
    obs = np.where(pos >= 0, series.index.to_numpy()[np.clip(pos, 0, None)], np.datetime64("NaT", "ns"))
    return vals, obs


def rolling_percentile(s: pd.Series, years: int) -> pd.Series:
    """信号日及之前 ``years`` 年内全部有效日值中 ``<= 当日值`` 的比例；不满窗口不出信号。"""
    valid = s.dropna()
    window = pd.Timedelta(days=365 * years + years // 4)
    if valid.empty:
        return pd.Series(np.nan, index=s.index)
    first = valid.index[0]
    x = valid.to_numpy()
    idx = valid.index
    lo = idx.searchsorted(idx - window, side="right")
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        if idx[i] - first < window:
            continue
        w = x[lo[i] : i + 1]
        out[i] = np.mean(w <= x[i])
    return pd.Series(out, index=idx).reindex(s.index)


def cash_accrual(r_cn: pd.Series) -> pd.Series:
    """第 t 日现金收益：上一交易日的 10Y 收益率按两交易日间的自然日数计息。"""
    days = r_cn.index.to_series().diff().dt.days
    return r_cn.shift(1) / 100.0 * days / 365.0


def ratchet(
    signal: pd.Series,
    ret: pd.Series,
    *,
    lag: int,
    cash: pd.Series | None = None,
    band: float = 0.10,
    band_tol: float = 1e-9,
    return_target: bool = False,
    one_way: bool = True,
    w0: float | None = None,
) -> pd.DataFrame:
    """``lag=1``：T 日信号 T+1 收盘成交；``lag=0``：T 日收盘成交（敏感性对照）。

    ``band``/``band_tol`` 原是脚本里的 ``BAND``/``BAND_TOL`` 常量，默认值即原值。
    ``return_target=True`` 时额外输出 ``target`` 列（成交日看到的目标），默认关闭，
    既有调用的输出与加参数前完全一致。

    ``one_way=False`` 去掉“分位 ≥ 0.5 只加、< 0.5 只减”的单向约束，目标即可成交仓位。
    ``w0`` 非 None 时是切片第一天之前的收盘仓位：第一天收益按它计算，之后照常漂移调仓。
    """
    dates = signal.index
    target = signal.shift(lag)  # 成交日看到的目标
    cash = pd.Series(0.0, index=dates) if cash is None else cash.reindex(dates)
    w = np.nan if w0 is None else float(w0)
    weights, trades, rets = [], [], []
    for i, d in enumerate(dates):
        r = ret.iloc[i]
        c = cash.iloc[i]
        # 当日收益按前一日收盘持仓计算，然后仓位漂移
        if not np.isnan(w):
            if np.isnan(r) or np.isnan(c):
                raise RuntimeError(f"持仓期间缺收益或缺现金利率: {d.date()}")
            port = w * r + (1 - w) * c
            w = w * (1 + r) / (1 + port)
        else:
            port = np.nan
        tgt = target.iloc[i]
        traded = 0.0
        if not np.isnan(tgt):
            if np.isnan(w):
                traded, w = tgt, tgt
            else:
                desired = (max(w, tgt) if tgt >= 0.5 else min(w, tgt)) if one_way else tgt
                if abs(desired - w) >= band - band_tol:
                    traded, w = abs(desired - w), desired
        weights.append(w)
        trades.append(traded)
        rets.append(port)
    out = pd.DataFrame({"w": weights, "turnover": trades, "ret": rets}, index=dates)
    if return_target:
        out["target"] = target.to_numpy()
    return out


def perf_daily(
    ret: pd.Series, extra: pd.DataFrame | None = None, rf: pd.Series | None = None
) -> dict[str, float]:
    ret = ret.dropna()
    nav = (1 + ret).cumprod()
    years = len(ret) / TRADING_DAYS
    ann = nav.iloc[-1] ** (1 / years) - 1
    vol = ret.std() * np.sqrt(TRADING_DAYS)
    out = {
        "ann_return": ann,
        "ann_vol": vol,
        "sharpe_rf0": ann / vol if vol else np.nan,
        "max_dd": (nav / nav.cummax() - 1).min(),
        "calmar": ann / abs((nav / nav.cummax() - 1).min()),
        "days": len(ret),
    }
    if rf is not None:
        excess = ret - rf.reindex(ret.index)
        out["sharpe_excess"] = excess.mean() / excess.std() * np.sqrt(TRADING_DAYS)
    if extra is not None:
        e = extra.loc[ret.index]
        out |= {
            "avg_w": e["w"].mean(),
            "trades_per_year": (e["turnover"] > 0).sum() / years,
            "turnover_per_year": e["turnover"].sum() / years,
        }
    return out


def nw_ols(y: pd.Series, x: pd.DataFrame, h: int):
    data = pd.concat([y.rename("y"), x], axis=1).dropna()
    fit = sm.OLS(data["y"], sm.add_constant(data[list(x.columns)])).fit(
        cov_type="HAC", cov_kwds={"maxlags": max(h, 1)}
    )
    return fit, len(data)


def clark_west(y: pd.Series, f_small: pd.Series, f_large: pd.Series, h: int) -> tuple[float, float]:
    f = (y - f_small) ** 2 - ((y - f_large) ** 2 - (f_small - f_large) ** 2)
    fit = sm.OLS(f.to_numpy(), np.ones(len(f))).fit(cov_type="HAC", cov_kwds={"maxlags": max(h, 1)})
    t = float(fit.tvalues[0])
    return t, float(1 - norm.cdf(t))


# %% [markdown]
# ## P1 统计工具：长期限收益、块自助法索引、IVX、零假设自助法、numpy 样本外
#
# 方案见 `docs/research/erp-phase2-plan.md` 的 P1 节。记号与 `2026-11-23-erp-rate-anchor.py`
# 的第二部分一致：月度样本 t = 0..n−1，`y1[t]` 是信号月 t 之后 1 个月的收益，
# `X[t]` 是信号月 t 的预测变量，h 个月远期收益是 `y1[t..t+h−1]` 的和（与原脚本的
# `fwd_h` 逐值相等）。以下函数只用于研究自检与 P1 正式计算，不改动上面已冻结的函数。


def forward_sum(y1: np.ndarray, h: int) -> np.ndarray:
    """``yh[t] = y1[t] + … + y1[t+h−1]``；窗口里任一项 NaN 即 NaN，窗口越界即 NaN。"""
    y = np.asarray(y1, dtype=float)
    if h < 1:
        raise ValueError(f"h 必须 >= 1: {h}")
    n = y.shape[0]
    out = np.full(n, np.nan)
    if n < h:
        return out
    bad = np.isnan(y)
    # 用「NaN 计数」前缀和判断窗口内是否有缺失，避免用 NaN 直接做 cumsum
    cs = np.concatenate(([0.0], np.cumsum(np.where(bad, 0.0, y))))
    cnt = np.concatenate(([0], np.cumsum(bad.astype(np.int64))))
    idx = np.arange(n - h + 1)
    total = cs[idx + h] - cs[idx]
    holes = cnt[idx + h] - cnt[idx]
    out[: n - h + 1] = np.where(holes > 0, np.nan, total)
    return out


def stationary_indices(n: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Politis–Romano 平稳自助法的循环索引，长度 n，取值 0..n−1。

    首个起点均匀抽取；之后每步以概率 ``1/mean_block`` 重新均匀抽起点（开始新块），
    否则取上一个索引 +1（模 n）。循环取值让任意位置的块都能覆盖到序列末尾。
    """
    if n < 1:
        raise ValueError(f"n 必须 >= 1: {n}")
    if not mean_block >= 1:
        raise ValueError(f"mean_block 必须 >= 1: {mean_block}")
    restart = rng.random(n) < 1.0 / mean_block
    starts = rng.integers(0, n, size=n)
    idx = np.empty(n, dtype=np.int64)
    idx[0] = rng.integers(0, n)
    for i in range(1, n):
        idx[i] = starts[i] if restart[i] else (idx[i - 1] + 1) % n
    return idx


def moving_block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """移动块自助法索引：均匀抽起点 ∈ [0, n−block]，拼接长 block 的连续块至长度 ≥ n 后截断。

    移动块不像平稳自助法那样循环取值，所以起点上限必须是 ``n−block``。
    """
    if not 1 <= block <= n:
        raise ValueError(f"块长必须在 [1, n] 内: block={block}, n={n}")
    n_blocks = -(-n // block)  # 向上取整
    starts = rng.integers(0, n - block + 1, size=n_blocks)
    idx = np.concatenate([np.arange(s, s + block) for s in starts])
    return idx[:n].astype(np.int64)


def _long_sum(a: np.ndarray, k: int) -> np.ndarray:
    """``out[i] = a[i] + … + a[i+k−1]``，i = 0..len(a)−k（列方向对二维逐列求和）。"""
    c = np.concatenate([np.zeros((1, *a.shape[1:])), np.cumsum(a, axis=0)])
    return c[k:] - c[: a.shape[0] - k + 1]


def _ivx_long_run_var(u: np.ndarray, eps: np.ndarray, nn: int) -> tuple[float, float]:
    """IVX 用到的两个标量长期方差：``Σεε`` 与 ``ΩFM``。

    ``ΩFM = Σεε − Ωεu Ωuu^{-1} Ωεu'`` 是去掉了「回归元更新与收益扰动同期相关」之后的
    远期收益方差，长期限的零分布靠它把 Stambaugh 偏差扣掉。
    """
    k = u.shape[1]
    sig_ee = float(eps @ eps) / nn
    sig_uu = u.T @ u / nn
    sig_eu = eps @ u / nn
    m = int(np.floor(nn ** (1 / 3)))  # Bartlett 带宽
    lam_uu = np.zeros((k, k))
    lam_eu = np.zeros(k)
    for j in range(1, m + 1):
        w = 1.0 - j / (m + 1)
        lam_uu += w * (u[j:].T @ u[: nn - j]) / nn
        lam_eu += w * (eps[j:] @ u[: nn - j]) / nn
    omega_uu = sig_uu + lam_uu + lam_uu.T
    omega_eu = sig_eu + lam_eu
    omega_fm = sig_ee - float(omega_eu @ np.linalg.solve(omega_uu, omega_eu))
    return sig_ee, omega_fm


def _ivx_instrument(
    x_lag: np.ndarray, x_t: np.ndarray, nn: int, beta: float, cz: float
) -> np.ndarray:
    """IVX 工具变量，返回滞后一期的 ``zz``（``zz[i] = z[i−1]``，``zz[0] = 0``）。

    ``z[i] = Rz·z[i−1] + Δx[i]``，``Rz = 1 + cz/nn^beta``：轻微向 1 收缩，既保留
    Δx 的差分（去趋势、去单位根）信息，又让它对水平值有持久记忆。
    """
    rz = 1.0 + cz / nn**beta
    dx = x_t - x_lag
    z = np.empty_like(dx)
    z[0] = dx[0]
    for i in range(1, nn):
        z[i] = rz * z[i - 1] + dx[i]
    return np.vstack([np.zeros((1, dx.shape[1])), z[: nn - 1]])


def _ivx_long_horizon(
    yt: np.ndarray,
    x_lag: np.ndarray,
    zz: np.ndarray,
    *,
    k_h: int,
    sig_ee: float,
    omega_fm: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    """长期限（K = h）的 IVX 汇总，返回 ``(coef, Q, nK)``。

    两处用了不同长度、不同聚合方式的工具，与 R 包 ``ivx`` 的 ``ivx_fit_cpp`` 保持一致：

    - 点估计与方差的三明治“面包”用**未聚合**的滞后工具 ``Z = zz[0:nK]``：``z[i−1]`` 只含
      到 ``u[i]`` 为止的更新，而 h 期收益和 ``YK[i]`` 的第一个扰动项 ``e[i]`` 与 ``u[i+1]``
      相关，二者不重叠，工具外生。
    - 三明治“肉”用 h 期聚合的 ``ZK``：``M = ZK'ZK·Σεε − nK·z̄K z̄K'·ΩFM``，前一项是
      工具的方差，后一项扣掉工具均值的贡献（均值非零的工具不能当作零均值处理）。

    两边都用 ``ZK`` 会出错：``ZK[i]`` 含 ``u[i..i+K−1]``，与 ``YK[i]`` 里的
    ``e[i..i+K−1]``（各与 ``u[i+1..i+K]`` 相关）区间重叠，工具不具外生性，
    拒绝率在零假设下高达 86%（`2026-11-24-erp-p1-tool-checks.py` 的 B 项会复现）。
    奇异时不猜，直接抛错。
    """
    nk = yt.shape[0] - k_h + 1
    yk = _long_sum(yt, k_h)
    xk = _long_sum(x_lag, k_h)
    z = zz[:nk]
    zk_sum = _long_sum(zz, k_h)
    yd = yk - yk.mean()
    xd = xk - xk.mean(axis=0)
    p_xz = xd.T @ z  # (k, k)，即 (Xd'Z)
    a = yd @ z  # (k,)，即 (Yd'Z)
    try:
        coef = np.linalg.solve(p_xz.T, a)  # (Yd'Z)(Xd'Z)^{-1}
    except np.linalg.LinAlgError as exc:  # pragma: no cover - 奇异时不猜测
        raise RuntimeError(f"IVX 的 (Xd'Z) 奇异: {exc}") from exc
    zbar = zk_sum.mean(axis=0)
    mm = (zk_sum.T @ zk_sum) * sig_ee - nk * np.outer(zbar, zbar) * omega_fm
    try:
        q = np.linalg.solve(p_xz.T, mm) @ np.linalg.inv(p_xz)
    except np.linalg.LinAlgError as exc:  # pragma: no cover
        raise RuntimeError(f"IVX 的 (Z'Xd) 奇异: {exc}") from exc
    return coef, q, nk


def ivx_wald(
    y1: np.ndarray,
    X: np.ndarray,
    h: int,
    *,
    beta: float = 0.95,
    cz: float = -1.0,
    cols: Sequence[int] | None = None,
) -> dict:
    """Kostakis–Magdalinos–Stamatogiannis (2015) IVX Wald 检验，含长期限（K = h）版本。

    按 R 包 ``ivx`` 的 ``ivx_fit`` 实现。只有一个回归元时额外给出 z 与单边正号 p 值，
    因为 ERP 的经济假设是有方向的（估值贵应压低未来收益）。

    记号：``nn = n−1``。本仓库的 ``y1[t]`` 已经是 ``X[t]`` 之后的收益，所以预测回归是
    ``yt = y1[0:nn]`` 对 ``Xlag = X[0:nn]``；``Xt = X[1:n]`` 只用来估回归元的 AR(1) 残差
    ``u``（``Xt[t]`` 相对 ``Xlag[t]`` 的更新）。``u`` 与 ``ε̂`` 在同一信号月上天然同期相关，
    这正是 Stambaugh 偏差的来源，也是长期限方差修正 ``ΩFM`` 要处理的东西。

    ``cols`` 指定检验用的列子集 S（默认全部），返回的 ``wald``/``p`` 对应
    ``W_S = A_S (Q_SS)^{-1} A_S'``，``coef`` 仍是全部 k 个系数。
    """
    y = np.asarray(y1, dtype=float)
    x = np.asarray(X, dtype=float)
    if x.ndim == 1:
        x = x[:, None]
    n = y.shape[0]
    if x.shape[0] != n:
        raise ValueError(f"y1 与 X 长度不一致: {n} vs {x.shape[0]}")
    assert not np.isnan(y).any(), "ivx_wald 的输入必须已去掉含 NaN 的样本"
    assert not np.isnan(x).any(), "ivx_wald 的输入必须已去掉含 NaN 的样本"
    nn = n - 1
    k = x.shape[1]
    K = int(h)
    nk = nn - K + 1
    if nn < 5 or nk < 5:
        raise ValueError(f"样本太短: nn={nn}, h={K}, 长期限观测数={nk}")

    x_lag = x[:nn]
    x_t = x[1:n]
    yt = y[:nn]

    # 受限的预测回归与每个回归元的 AR(1)
    eps = sm.OLS(yt, np.column_stack([np.ones(nn), x_lag])).fit().resid
    rn = (x_lag * x_t).sum(axis=0) / (x_lag * x_lag).sum(axis=0)
    u = x_t - x_lag * rn

    sig_ee, omega_fm = _ivx_long_run_var(u, eps, nn)
    zz = _ivx_instrument(x_lag, x_t, nn, beta, cz)
    coef, q, nk = _ivx_long_horizon(yt, x_lag, zz, k_h=K, sig_ee=sig_ee, omega_fm=omega_fm)

    sub = np.arange(k) if cols is None else np.asarray(list(cols), dtype=np.int64)
    a_s = coef[sub]
    try:
        wald = float(a_s @ np.linalg.solve(q[np.ix_(sub, sub)], a_s))
    except np.linalg.LinAlgError as exc:  # pragma: no cover
        raise RuntimeError(f"IVX 的 Q 子阵奇异: {exc}") from exc
    df = int(sub.shape[0])
    out = {
        "coef": coef,
        "wald": wald,
        "p": float(1 - chi2.cdf(wald, df)),
        "n": int(nk),
        "df": df,
        "cols": tuple(int(c) for c in sub),
    }
    if df == 1:
        zs = float(np.sign(a_s[0]) * np.sqrt(wald))
        out["z"] = zs
        out["p_one_sided_pos"] = float(1 - norm.cdf(zs))
    return out


def null_bootstrap_draw(
    y1: np.ndarray,
    X: np.ndarray,
    keep_cols: Sequence[int],
    idx: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """零假设（``keep_cols`` 之外无预测力）下生成一组自助样本。

    做法：受限模型给 ``ε̂``，回归元的 VAR(1) 给 ``u``，两者按行配对后用平稳自助法联合重抽
    —— 联合是为了保留收益扰动与回归元更新之间的相关性，Stambaugh 偏差正是来自这里。

    对齐：``ε̂[t]`` 是信号月 t 的收益扰动（即 t+1 月的实现收益），``u[t]`` 是
    ``X`` 从 t 到 t+1 的更新，两者都在 t+1 月实现，所以同一下标 i 配对
    （``ε̂[i]`` 对 ``u[i]``，等价于文字上的 ``ε̂[t−1]`` 对 ``u[t]``）。``ε̂`` 与 ``u``
    都是长度 n−1，``idx`` 也必须长度 n−1。

    ``y1*[n−1] = NaN``：与真实数据末月远期收益缺失的形状保持一致；用到 ``yh`` 的检验
    （``ivx_wald``/NW 回归）本来就会丢掉这一个观测。
    """
    y = np.asarray(y1, dtype=float)
    x = np.asarray(X, dtype=float)
    if x.ndim == 1:
        x = x[:, None]
    n = x.shape[0]
    if y.shape[0] != n:
        raise ValueError(f"y1 与 X 长度不一致: {y.shape[0]} vs {n}")
    nn = n - 1
    keep = list(keep_cols)
    order = np.asarray(idx, dtype=np.int64)
    if order.shape != (nn,):
        raise ValueError(f"idx 长度必须是 n−1={nn}: {order.shape}")
    if order.min() < 0 or order.max() >= nn:
        raise ValueError("idx 越界")

    # 受限模型 y1 = μ + X[keep]·b + ε，只用 t = 0..n−2
    xs = x[:nn][:, keep]
    design_b = np.column_stack([np.ones(nn), xs])
    coef_b = np.linalg.lstsq(design_b, y[:nn], rcond=None)[0]
    eps = y[:nn] - design_b @ coef_b

    # 回归元的 VAR(1)：X[t] = c + Φ X[t−1] + u[t]，t = 1..n−1
    design_v = np.column_stack([np.ones(nn), x[:nn]])
    target_v = x[1:n]
    coef_v = np.linalg.lstsq(design_v, target_v, rcond=None)[0]
    c_hat = coef_v[0]
    phi = coef_v[1:].T  # (k, k)，使 X[t] = c + Φ X[t−1] + u[t]
    u = target_v - design_v @ coef_v

    u_star = u[order]  # 对齐 t = 1..n−1
    e_star = eps[order]  # 对齐 t = 0..n−2
    x_star = np.empty_like(x)
    x_star[0] = x[0]
    for t in range(1, n):
        x_star[t] = c_hat + phi @ x_star[t - 1] + u_star[t - 1]
    y_star = np.full(n, np.nan)
    fitted = coef_b[0] + (x_star[:nn][:, keep] @ coef_b[1:] if keep else 0.0)
    y_star[:nn] = fitted + e_star
    return y_star, x_star


def oos_expanding(
    yh: np.ndarray,
    X: np.ndarray,
    h: int,
    *,
    train_start: int,
    oos_start: int,
    min_history: int,
) -> pd.DataFrame:
    """扩张窗口样本外预测（numpy 版），语义与原脚本 ``oos_forecasts`` 一致。

    对每个预测月 i ≥ ``oos_start``（``yh[i]`` 非 NaN 且 ``X[i]`` 无 NaN）：
    训练月 q 必须满足 ``q+h+1 ≤ i``，即 h 期收益在 i 的**信号日**（该月最后一个交易日）
    之前已经实现。原实现按日期判断（``realized[q] = 第 q+h+1 月的首个交易日``，要求
    ``<= 信号日``），差一个月：第 q+h+1 月的首个交易日必然晚于第 i 月的最后一个交易日，
    所以 ``q+h+1 ≤ i``，即上界是 ``i−h−1`` 而不是 ``i−h``。

    ``M0`` 用「``yh`` 非 NaN」的训练月算均值（原实现如此），回归模型额外要求 ``X`` 无 NaN。
    ``slope`` 是 k=1 时的斜率，k>1 时给第一列的斜率。
    """
    y = np.asarray(yh, dtype=float)
    x = np.asarray(X, dtype=float)
    if x.ndim == 1:
        x = x[:, None]
    n = y.shape[0]
    if x.shape[0] != n:
        raise ValueError(f"yh 与 X 长度不一致: {n} vs {x.shape[0]}")
    rows = []
    for i in range(int(oos_start), n):
        if np.isnan(y[i]) or np.isnan(x[i]).any():
            continue
        last = i - h - 1  # 训练月上限，见上面的「已实现」说明
        if last < train_start:
            continue
        span = np.arange(int(train_start), last + 1)
        base = span[~np.isnan(y[span])]
        if len(base) < min_history:
            continue
        m0 = float(y[base].mean())
        ok = base[~np.isnan(x[base]).any(axis=1)]
        row = {"i": i, "y": float(y[i]), "M0": m0}
        if len(ok) < min_history:
            row["model"], row["slope"] = np.nan, np.nan
            rows.append(row)
            continue
        design = np.column_stack([np.ones(len(ok)), x[ok]])
        coef = np.linalg.lstsq(design, y[ok], rcond=None)[0]
        row["model"] = float(coef[0] + x[i] @ coef[1:])
        row["slope"] = float(coef[1])
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=["y", "M0", "model", "slope"], index=pd.Index([], name="i"))
    return pd.DataFrame(rows).set_index("i")[["y", "M0", "model", "slope"]]


def r2_os(y: np.ndarray, f: np.ndarray, f0: np.ndarray) -> float:
    """样本外 R²：1 − Σ(y−f)² / Σ(y−f0)²。``f0`` 是基准（历史均值）预测。"""
    y = np.asarray(y, dtype=float)
    f = np.asarray(f, dtype=float)
    f0 = np.asarray(f0, dtype=float)
    return float(1 - ((y - f) ** 2).sum() / ((y - f0) ** 2).sum())


def clark_west_np(y: np.ndarray, f0: np.ndarray, f1: np.ndarray, h: int) -> tuple[float, float]:
    """``clark_west`` 的 numpy 版（与它同口径：NW 滞后 max(h,1)，单边 p）。

    ``f0`` 是嵌套小模型（历史均值）预测，``f1`` 是大模型预测。
    """
    y = np.asarray(y, dtype=float)
    f0 = np.asarray(f0, dtype=float)
    f1 = np.asarray(f1, dtype=float)
    f = (y - f0) ** 2 - ((y - f1) ** 2 - (f0 - f1) ** 2)
    fit = sm.OLS(f, np.ones(len(f))).fit(cov_type="HAC", cov_kwds={"maxlags": max(h, 1)})
    t = float(fit.tvalues[0])
    return t, float(1 - norm.cdf(t))
