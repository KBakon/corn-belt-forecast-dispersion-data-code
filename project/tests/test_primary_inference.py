"""Independent synthetic checks of frozen fixed effects and cluster algebra."""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.linalg as la
import statsmodels.api as sm
from pyproj import Geod
from statsmodels.stats.sandwich_covariance import cov_cluster_2groups

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from primary_inference import (conley_hac_state_centroids, cr2_satterthwaite_state,
                               fit_model, tost_equivalence, wild_state_bootstrap_t)


def synthetic_panel():
    rng = np.random.default_rng(1402)
    rows = []
    for year in range(2000, 2005):
        first = pd.date_range(f"{year}-03-01", periods=1, freq="W-SUN")[0]
        for week in range(14, 19):
            for state in range(8):
                rows.append({"state_postal": f"S{state:02d}", "crop_year": year,
                             "week_ending_sunday": first + pd.Timedelta(days=7 * (week - 14)),
                             "seasonal_week": week, "gefs_precip_sd5_iqr": rng.normal(),
                             "gefs_precip_mean_iqr": rng.normal(),
                             "dsfw_days": rng.uniform(1, 7),
                             "nldas_precip_total_mm": rng.uniform(0, 90),
                             "nldas_tair_mean_c": rng.normal(15, 6),
                             "nldas_soilm_0_10_mean_kgm2": rng.uniform(15, 40),
                             "remaining_start_pp": rng.uniform(5, 95)})
    frame = pd.DataFrame(rows)
    state_effect = {key: rng.normal() for key in
                    (frame.state_postal + "|" + frame.seasonal_week.astype(str)).unique()}
    year_effect = {key: rng.normal() for key in
                   (frame.crop_year.astype(str) + "|" + frame.seasonal_week.astype(str)).unique()}
    frame["planting_utilization_pp_per_suitable_day"] = (
        0.4 * frame.gefs_precip_sd5_iqr + 0.1 * frame.gefs_precip_mean_iqr +
        0.07 * frame.dsfw_days +
        (frame.state_postal + "|" + frame.seasonal_week.astype(str)).map(state_effect) +
        (frame.crop_year.astype(str) + "|" + frame.seasonal_week.astype(str)).map(year_effect) +
        rng.normal(0, 0.5, len(frame)))
    return frame


class PrimaryInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fit = fit_model(synthetic_panel())

    def test_exact_fe_and_two_way_cluster_match_statsmodels(self):
        fit = self.fit
        frame = fit.frame
        state_week = frame.state_postal + "|" + frame.seasonal_week.astype(str)
        year_week = frame.crop_year.astype(str) + "|" + frame.seasonal_week.astype(str)
        for labels in (state_week, year_week):
            sums = pd.Series(fit.residual).groupby(labels).sum()
            self.assertLess(float(sums.abs().max()), 1e-7)
        fe = np.column_stack([pd.get_dummies(state_week, dtype=float).to_numpy(),
                              pd.get_dummies(year_week, dtype=float).to_numpy()])
        norms = np.linalg.norm(fe, axis=0)
        _, r, pivot = la.qr(fe / norms, mode="economic", pivoting=True)
        rank = int(np.sum(np.abs(np.diag(r)) > 1e-10))
        self.assertEqual(rank, fit.rank_fe)
        x = np.column_stack([fit.ar + fit.qfe @ (fit.qfe.T @ fit.ar), fe[:, pivot[:rank]]])
        # The numeric block above is FE-residualized; it spans the same full design.
        model = sm.OLS(fit.y, x).fit()
        group = np.column_stack([fit.state_codes, fit.date_codes])
        covariance, _, _ = cov_cluster_2groups(model, group, use_correction=True)
        self.assertAlmostEqual(float(model.params[0]), float(fit.beta[0]), places=7)
        self.assertAlmostEqual(float(covariance[0, 0]), float(fit.vcov_two_way[0, 0]), places=7)

    def test_restricted_wild_bootstrap_and_tost_are_reproducible(self):
        first = wild_state_bootstrap_t(self.fit, seed=77, replications=199)
        second = wild_state_bootstrap_t(self.fit, seed=77, replications=199)
        self.assertEqual(first, second)
        self.assertGreaterEqual(first["two_sided_p"], 1 / 200)
        self.assertLessEqual(first["two_sided_p"], 1)
        equivalence = tost_equivalence(self.fit)
        self.assertEqual(equivalence["equivalent"],
                         equivalence["ci90_lower"] > -0.5 and equivalence["ci90_upper"] < 0.5)

    def test_cr2_moment_identity_and_conley_pairwise_kernel(self):
        fit = self.fit
        cr2 = cr2_satterthwaite_state(fit)
        self.assertLess(cr2["working_moment_relative_error"], 1e-8)
        states = sorted(fit.frame.state_postal.unique())
        centroids = {state: (-100 + i, 40) for i, state in enumerate(states)}
        conley = conley_hac_state_centroids(fit, centroids)
        geod = Geod(ellps="WGS84")
        kernel = np.zeros((len(states), len(states)))
        for i, state_i in enumerate(states):
            for j, state_j in enumerate(states):
                _, _, meters = geod.inv(*centroids[state_i], *centroids[state_j])
                kernel[i, j] = max(0, 1 - meters / 500000)
        influence = fit.d * fit.residual / fit.dtd
        date = pd.to_datetime(fit.frame.week_ending_sunday)
        days = np.abs((date.to_numpy()[:, None] - date.to_numpy()[None, :]) /
                      np.timedelta64(1, "D"))
        time_kernel = np.where(days == 0, 1.0, np.where(days == 7, 0.5, 0.0))
        pairwise = (influence[:, None] * influence[None, :] *
                    kernel[fit.state_codes[:, None], fit.state_codes[None, :]] *
                    time_kernel).sum()
        self.assertAlmostEqual(conley["se"] ** 2, float(pairwise), places=9)


if __name__ == "__main__":
    unittest.main()
