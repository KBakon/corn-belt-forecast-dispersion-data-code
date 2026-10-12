"""Frozen two-way-FE OLS and dependence-robust inference for P1-M2."""

from dataclasses import dataclass
import hashlib

import numpy as np
import pandas as pd
from scipy import linalg, stats


NUMERIC_NAMES = ("dispersion_iqr", "forecast_mean_iqr", "dsfw_days", "dsfw_days_squared",
                 "realized_precip_mm", "realized_tair_c", "realized_soilm_kgm2",
                 "remaining_start_pp", "remaining_start_pp_squared")
BOOTSTRAP_SEED = 20261007
BOOTSTRAP_REPLICATIONS = 9999


@dataclass
class Fit:
    frame: pd.DataFrame
    names: tuple
    beta: np.ndarray
    vcov_two_way: np.ndarray
    vcov_state: np.ndarray
    se_two_way: np.ndarray
    df_two_way: int
    residual: np.ndarray
    y: np.ndarray
    ar: np.ndarray
    yr: np.ndarray
    qfe: np.ndarray
    qx: np.ndarray
    bread: np.ndarray
    d: np.ndarray
    e0: np.ndarray
    dtd: float
    state_codes: np.ndarray
    date_codes: np.ndarray
    rank_fe: int
    rank_total: int
    numeric_condition_number: float
    r_squared: float
    weights: np.ndarray


def _fe_basis(frame, sqrt_weight):
    state_week = frame.state_postal.astype(str) + "|" + frame.seasonal_week.astype(str)
    year_week = frame.crop_year.astype(str) + "|" + frame.seasonal_week.astype(str)
    first = pd.get_dummies(state_week, prefix="state_week", dtype=float)
    second = pd.get_dummies(year_week, prefix="year_week", dtype=float)
    fe = np.concatenate([first.to_numpy(), second.to_numpy()], axis=1)
    fe *= sqrt_weight[:, None]
    column_norm = np.linalg.norm(fe, axis=0)
    if np.any(column_norm <= 0):
        raise ValueError("Observed fixed-effect category has zero support")
    q, r, _ = linalg.qr(fe / column_norm, mode="economic", pivoting=True,
                        check_finite=False)
    diagonal = np.abs(np.diag(r))
    rank = int(np.sum(diagonal > max(diagonal[0] * 1e-10, 1e-12)))
    if rank <= 0:
        raise ValueError("State-week/year-week fixed effects have zero rank")
    return q[:, :rank], rank, first.shape[1], second.shape[1]


def _numeric(frame, dispersion, forecast_mean, soil, precip, tair):
    dsfw = frame.dsfw_days.to_numpy(float)
    remaining = frame.remaining_start_pp.to_numpy(float)
    return np.column_stack((
        frame[dispersion].to_numpy(float), frame[forecast_mean].to_numpy(float),
        dsfw, dsfw ** 2, frame[precip].to_numpy(float), frame[tair].to_numpy(float),
        frame[soil].to_numpy(float), remaining, remaining ** 2))


def _cluster_cov(ar, residual, bread, codes, rank_total):
    n = len(residual)
    group_count = int(codes.max()) + 1
    if group_count <= 1 or n <= rank_total:
        raise ValueError("Insufficient cluster groups or residual degrees of freedom")
    scores = np.zeros((group_count, ar.shape[1]), dtype=float)
    np.add.at(scores, codes, ar * residual[:, None])
    correction = (group_count / (group_count - 1)) * ((n - 1) / (n - rank_total))
    return correction * bread @ (scores.T @ scores) @ bread


def fit_model(frame, *, outcome="planting_utilization_pp_per_suitable_day",
              dispersion="gefs_precip_sd5_iqr", forecast_mean="gefs_precip_mean_iqr",
              soil="nldas_soilm_0_10_mean_kgm2", precip="nldas_precip_total_mm",
              tair="nldas_tair_mean_c", weights=None):
    if frame.duplicated(["state_postal", "week_ending_sunday"]).any():
        raise ValueError("Duplicate state/week observation")
    ordered = frame.sort_values(["state_postal", "week_ending_sunday"]).reset_index(drop=True)
    n = len(ordered)
    w = np.ones(n) if weights is None else np.asarray(weights(ordered), dtype=float)
    if len(w) != n or not np.isfinite(w).all() or np.any(w <= 0):
        raise ValueError("Regression weights must be positive, finite, and complete")
    w = w / w.mean()
    sqrtw = np.sqrt(w)
    y = ordered[outcome].to_numpy(float) * sqrtw
    a = _numeric(ordered, dispersion, forecast_mean, soil, precip, tair) * sqrtw[:, None]
    if not np.isfinite(a).all() or not np.isfinite(y).all():
        raise ValueError("Selected model frame has a missing or infinite primary variable")
    qfe, rank_fe, state_week_count, year_week_count = _fe_basis(ordered, sqrtw)
    ar = a - qfe @ (qfe.T @ a)
    yr = y - qfe @ (qfe.T @ y)
    column_norms = np.linalg.norm(ar, axis=0)
    if np.any(column_norms <= 1e-8):
        raise ValueError("A numeric regressor is unidentifiable after fixed effects")
    scaled = ar / column_norms
    qnum, rnum = linalg.qr(scaled, mode="economic", check_finite=False)
    if np.linalg.matrix_rank(rnum, tol=1e-10) != len(NUMERIC_NAMES):
        raise ValueError("Frozen numeric regressors are rank deficient")
    scaled_beta = linalg.solve_triangular(rnum, qnum.T @ yr, check_finite=False)
    beta = scaled_beta / column_norms
    residual = yr - ar @ beta
    bread = (np.diag(1 / column_norms) @
             linalg.inv(rnum.T @ rnum, check_finite=False) @
             np.diag(1 / column_norms))
    rank_total = rank_fe + len(NUMERIC_NAMES)
    states, _ = pd.factorize(ordered.state_postal, sort=True)
    dates, _ = pd.factorize(pd.to_datetime(ordered.week_ending_sunday), sort=True)
    intersections, _ = pd.factorize(pd.MultiIndex.from_arrays([states, dates]))
    vc_state = _cluster_cov(ar, residual, bread, states, rank_total)
    vc_date = _cluster_cov(ar, residual, bread, dates, rank_total)
    vc_intersection = _cluster_cov(ar, residual, bread, intersections, rank_total)
    vc_two = vc_state + vc_date - vc_intersection
    if vc_two[0, 0] <= 0 or not np.isfinite(vc_two[0, 0]):
        raise ValueError("Two-way clustered focal variance is nonpositive or nonfinite")
    qother, _ = linalg.qr(ar[:, 1:], mode="economic", check_finite=False)
    d = ar[:, 0] - qother @ (qother.T @ ar[:, 0])
    e0 = yr - qother @ (qother.T @ yr)
    dtd = float(d @ d)
    if not np.isclose(beta[0], (d @ e0) / dtd, rtol=1e-8, atol=1e-9):
        raise ValueError("Focal coefficient fails partial-regression identity")
    qx = np.column_stack([qfe, qnum])
    if np.linalg.norm(qx.T @ residual, ord=np.inf) > 1e-6:
        raise ValueError("OLS residual is not orthogonal to exact fixed effects and regressors")
    y_mean = np.average(ordered[outcome].to_numpy(float), weights=w)
    total = np.sum(w * (ordered[outcome].to_numpy(float) - y_mean) ** 2)
    r_squared = float(1 - (residual @ residual) / total)
    return Fit(ordered, NUMERIC_NAMES, beta, vc_two, vc_state,
               np.sqrt(np.maximum(0, np.diag(vc_two))),
               min(int(states.max()), int(dates.max())), residual, y, ar, yr,
               qfe, qx, bread, d, e0, dtd, states, dates, rank_fe, rank_total,
               float(np.linalg.cond(scaled)), r_squared, w)


def coefficient_table(fit):
    table = []
    residual_df = len(fit.y) - fit.rank_total
    classical_variance = float(fit.residual @ fit.residual) / residual_df
    for index, name in enumerate(fit.names):
        estimate = float(fit.beta[index])
        se = float(fit.se_two_way[index])
        classical_se = float(np.sqrt(classical_variance * fit.bread[index, index]))
        classical_critical = float(stats.t.ppf(0.975, residual_df))
        if se > 0:
            crit = stats.t.ppf(0.975, fit.df_two_way)
            p = float(2 * stats.t.sf(abs(estimate / se), fit.df_two_way))
            lo, hi = estimate - crit * se, estimate + crit * se
        else:
            p = lo = hi = float("nan")
        table.append({"term": name, "coefficient": estimate, "two_way_cluster_se": se,
                      "two_way_cluster_df": fit.df_two_way,
                      "two_sided_p": p, "ci95_lower": lo, "ci95_upper": hi,
                      "classical_ols_se": classical_se,
                      "classical_ols_two_sided_p": float(2 * stats.t.sf(abs(estimate / classical_se), residual_df)),
                      "classical_ols_ci95_lower": estimate - classical_critical * classical_se,
                      "classical_ols_ci95_upper": estimate + classical_critical * classical_se})
    return table


def wild_state_bootstrap_t(fit, seed=BOOTSTRAP_SEED, replications=BOOTSTRAP_REPLICATIONS):
    groups = int(fit.state_codes.max()) + 1
    n = len(fit.y)
    correction = (groups / (groups - 1)) * ((n - 1) / (n - fit.rank_total))
    a = np.bincount(fit.state_codes, weights=fit.d * fit.e0,
                    minlength=groups) / fit.dtd
    h = np.zeros((groups, groups), dtype=float)
    for source_group in range(groups):
        shifted = np.where(fit.state_codes == source_group, fit.e0, 0.0)
        unrestricted_residual = shifted - fit.qx @ (fit.qx.T @ shifted)
        h[:, source_group] = np.bincount(
            fit.state_codes, weights=fit.d * unrestricted_residual,
            minlength=groups)
    rng = np.random.default_rng(seed)
    draws = (2 * rng.integers(0, 2, size=(replications, groups), dtype=np.int8) - 1)
    betas = draws @ a
    scores = draws @ h.T
    ses = np.sqrt(correction * np.sum(scores ** 2, axis=1)) / fit.dtd
    if np.any(ses <= 0) or not np.isfinite(ses).all():
        raise ValueError("Wild bootstrap produced nonpositive studentizing variance")
    bootstrap_t = betas / ses
    observed_se = float(np.sqrt(fit.vcov_state[0, 0]))
    observed_t = float(fit.beta[0] / observed_se)
    extreme = int(np.sum(np.abs(bootstrap_t) >= abs(observed_t)))
    p = (1 + extreme) / (replications + 1)
    return {"seed": seed, "rng": "NumPy PCG64", "replications": replications,
            "cluster": "state", "null": "beta_dispersion=0, restricted",
            "weights": "Rademacher +/-1", "studentization": "state-cluster CRV1",
            "observed_state_cluster_se": observed_se, "observed_t": observed_t,
            "two_sided_p": float(p), "extreme_replications": extreme,
            "draws_sha256": hashlib.sha256(draws.tobytes()).hexdigest(),
            "state_clusters": groups}


def tost_equivalence(fit, bound=0.5):
    estimate, se, df = float(fit.beta[0]), float(fit.se_two_way[0]), fit.df_two_way
    critical = stats.t.ppf(0.95, df)
    lo, hi = estimate - critical * se, estimate + critical * se
    p_lower = float(stats.t.sf((estimate + bound) / se, df))
    p_upper = float(stats.t.cdf((estimate - bound) / se, df))
    return {"bound_lower": -bound, "bound_upper": bound, "alpha": 0.05,
            "ci90_lower": float(lo), "ci90_upper": float(hi),
            "p_lower_one_sided": p_lower, "p_upper_one_sided": p_upper,
            "tost_p": max(p_lower, p_upper),
            "equivalent": bool(lo > -bound and hi < bound)}


def cr2_satterthwaite_state(fit):
    """Bell-McCaffrey CR2 for the focal contrast under an identity working model."""
    groups = int(fit.state_codes.max()) + 1
    influence_rows = []
    adjusted_scores = []
    removed_null_dimensions = 0
    for group in range(groups):
        mask = fit.state_codes == group
        local_q = fit.qx[mask]
        local_m = np.eye(mask.sum()) - local_q @ local_q.T
        eigenvalues, eigenvectors = linalg.eigh(local_m, check_finite=False)
        cutoff = max(1e-10, float(eigenvalues.max()) * 1e-8)
        positive = eigenvalues > cutoff
        removed_null_dimensions += int((~positive).sum())
        if not positive.any():
            raise ValueError("CR2 state cluster has no residual support")
        adjustment = (eigenvectors[:, positive] *
                      (1 / np.sqrt(eigenvalues[positive]))) @ eigenvectors[:, positive].T
        local_contrast = fit.ar[mask] @ fit.bread[:, 0]
        adjusted_scores.append(float(local_contrast @ adjustment @ fit.residual[mask]))
        embedded = np.zeros(len(fit.y))
        embedded[mask] = adjustment @ local_contrast
        influence_rows.append(embedded - fit.qx @ (fit.qx.T @ embedded))
    influence = np.vstack(influence_rows)
    gram = influence @ influence.T
    working_expectation = float(np.trace(gram))
    target = float(fit.bread[0, 0])
    relative_bias = abs(working_expectation - target) / target
    if relative_bias > 1e-5:
        raise ValueError(f"CR2 working-model moment identity fails: relative error {relative_bias}")
    variance = float(np.sum(np.square(adjusted_scores)))
    degrees = working_expectation ** 2 / float(np.sum(gram ** 2))
    if variance <= 0 or degrees <= 1 or not np.isfinite(degrees):
        raise ValueError("CR2 variance or Satterthwaite degrees of freedom invalid")
    se = float(np.sqrt(variance))
    tstat = float(fit.beta[0] / se)
    critical = float(stats.t.ppf(0.975, degrees))
    return {"status": "computed", "cluster": "state", "working_covariance": "identity",
            "adjustment": "CR2 inverse square root on estimable residual subspace",
            "state_clusters": groups, "null_directions_removed": removed_null_dimensions,
            "working_moment_relative_error": relative_bias, "se": se,
            "satterthwaite_df": float(degrees), "t": tstat,
            "two_sided_p": float(2 * stats.t.sf(abs(tstat), degrees)),
            "ci95_lower": float(fit.beta[0] - critical * se),
            "ci95_upper": float(fit.beta[0] + critical * se)}


def conley_hac_state_centroids(fit, centroid_lonlat, cutoff_km=500, lag_weeks=1):
    """Bartlett Conley HAC for 500-km space and one-week time support."""
    from pyproj import Geod

    states = sorted(fit.frame.state_postal.unique())
    if set(states) != set(centroid_lonlat):
        raise ValueError("Conley centroid state set differs from model state set")
    geod = Geod(ellps="WGS84")
    space = np.zeros((len(states), len(states)))
    for i, state_i in enumerate(states):
        for j, state_j in enumerate(states):
            lon_i, lat_i = centroid_lonlat[state_i]
            lon_j, lat_j = centroid_lonlat[state_j]
            _, _, meters = geod.inv(lon_i, lat_i, lon_j, lat_j)
            space[i, j] = max(0.0, 1.0 - (meters / 1000) / cutoff_km)
    dates = pd.DatetimeIndex(sorted(pd.to_datetime(fit.frame.week_ending_sunday).unique()))
    if len(dates) != int(fit.date_codes.max()) + 1:
        raise ValueError("Conley date grouping differs from primary week clusters")
    grid = np.zeros((len(dates), len(states)))
    influence = fit.d * fit.residual / fit.dtd
    np.add.at(grid, (fit.date_codes, fit.state_codes), influence)
    variance = float(np.einsum("ti,ij,tj->", grid, space, grid))
    for lag in range(1, lag_weeks + 1):
        temporal_weight = 1 - lag / (lag_weeks + 1)
        for t in range(len(dates) - lag):
            if (dates[t + lag] - dates[t]).days == 7 * lag:
                variance += 2 * temporal_weight * float(grid[t] @ space @ grid[t + lag])
    if variance <= 0 or not np.isfinite(variance):
        raise ValueError("Conley HAC focal variance is nonpositive or nonfinite")
    se = float(np.sqrt(variance))
    z = float(fit.beta[0] / se)
    return {"status": "computed", "centroids": "2019 TIGER state geometry",
            "distance": "WGS84 geodesic", "spatial_kernel": "Bartlett",
            "spatial_cutoff_km": cutoff_km, "temporal_kernel": "Bartlett",
            "temporal_lag_weeks": lag_weeks, "se": se, "z": z,
            "normal_approx_two_sided_p": float(2 * stats.norm.sf(abs(z)))}
