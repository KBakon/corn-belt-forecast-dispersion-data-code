**Table 3. Prespecified specification and inference sensitivities**

**Panel A. Five specification sensitivities**

| Specification | N | Coefficient | Two-way clustered 95% CI | Outcome unit / dispersion scaling |
| :--- | ---: | ---: | :--- | :--- |
| Acreage-weighted OLS | 1,777 | +0.1736331961 | [-0.0623969831, 0.4096633753] | pp of total acreage / suitable day; primary pooled IQR |
| Direct weekly planting increment | 1,777 | +0.4313266675 | [-0.0599098828, 0.9225632179] | pp of total acreage / week; primary pooled IQR |
| Fixed ISO weeks 14–24 | 2,588 | +0.0679615281 | [-0.0454097245, 0.1813327806] | pp of total acreage / suitable day; primary pooled IQR |
| Start-of-window soil moisture | 1,777 | +0.1361619070 | [-0.0106933063, 0.2830171202] | pp of total acreage / suitable day; primary pooled IQR |
| State-land-area meteorological weighting | 1,777 | +0.1231139797 | [-0.0669524096, 0.3131803689] | pp of total acreage / suitable day; own land-area pooled IQR |

**Panel B. Inference sensitivities for the unchanged primary coefficient**

| Covariance procedure | SE | 95% CI | Two-sided p-value |
| :--- | ---: | :--- | ---: |
| State-cluster CR2 / Satterthwaite (df = 13.165053) | 0.0560072272 | [0.0145064110, 0.2561908823] | 0.0308894860 |
| Conley 500 km / 1 week (normal approximation) | 0.0588363444 | Not reported | 0.0214241065 |

*Note:* Panel A confidence intervals use the specified two-way state/date clustering. All five point estimates are positive and all five 95% intervals include zero. The weekly-increment row uses a different outcome and must not be compared numerically as a per-suitable-day effect. The land-area row uses a separately defined pooled dispersion IQR (6.6627890 mm; primary crop-weighted IQR 7.4037603 mm). Panel B changes covariance estimation for the same primary coefficient; these are sensitivities, not replacements for primary two-way clustered and wild-bootstrap inference. A Conley confidence interval is not reported because it was not part of the recorded sensitivity output.
