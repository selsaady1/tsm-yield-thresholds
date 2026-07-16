# Yield Data Sources for Model Calibration

Purpose: ground the model's yield parameters in published figures, to address the
reviewers' concern that the model used synthetic data.

Every source below was confirmed to exist via web search on 2026-07-05, and the figure
quoted is the figure the source actually states. Two URLs that appeared in an earlier draft
of this note (a newsletter and a blog) could not be verified and have been removed; they were
never cited in the manuscript.

## Front-End (wafer / die) yield
- In production, net good dies are typically 60-95% of gross, depending on die size and
  defect density; yield is commonly modeled with Murphy's or the Poisson model.
- Our calibrated Front-End mean of 0.90 lies within this range.
- Source (verified): Silicon Analysts, "How Many Chips Per Wafer? GDPW Calculator & Die Yield
  Guide," https://siliconanalysts.com/guide/chips-per-wafer

## Back-End (assembly / packaging / test) yield
- Established assembly processes report yields above 99% (source wording: "typically greater
  than 99 percent"); assembly-related electrical fallout is typically under 0.5%. The
  manuscript now uses this exact wording.
- Calibrated Back-End realistic case: mean ~0.98, tight range ~0.96-0.99 (used only as an
  additional case; the paper keeps 0.70-0.90 as the baseline).
- Source (verified): "The back-end process," Semiconductor Digest,
  https://sst.semiconductor-digest.com/2000/10/the-back-end-process-step-9/
- Additional verified industry reference on test: AnySilicon, "Understanding semiconductor
  testing," https://anysilicon.com/understanding-semiconductor-testing/

## Yield distribution shape (for the continuous-distribution experiment)
- The two-point (low/high) yield is replaced with a continuous Beta distribution on [0,1],
  discretized into equal-probability points and matched to the same mean and standard
  deviation. Beta is the standard bounded choice; the Murphy/Poisson defect-density models
  cited above motivate a bounded, skewed shape.

## Note on an optional case-study dataset (NOT used or cited in the manuscript)
- WM-811K / LSWMD is a public wafer-map dataset that could support an empirical case study in
  a future revision. It is not used or cited in the current manuscript. If you decide to use
  it, confirm the exact hosting URL before citing.
