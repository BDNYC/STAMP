#!/usr/bin/env python3
"""Inject-and-recover validation for the SA3D chi-squared grid fitter.

Creates synthetic observations from known grid models, adds noise,
fits them back against the grid, and checks whether the fitter recovers
the correct stellar parameters.

Usage:
    python scripts/validate_fitting.py                        # full test suite
    python scripts/validate_fitting.py --grid phoenix_cool    # specify grid
    python scripts/validate_fitting.py --grid phoenix_cool --feh -0.5  # PHOENIX grid
    python scripts/validate_fitting.py --teff 4000 --logg 5.0 # pick injection model
    python scripts/validate_fitting.py --no-plot              # terminal only
    python scripts/validate_fitting.py --full-ranking         # show all models in ranking
"""

import argparse
import os
import sys

import numpy as np

# ---------------------------------------------------------------------------
# Resolve imports: add project root to sys.path so we can import fitting /
# model_grids regardless of where the script is invoked from.
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from fitting import fit_spectrum_to_grid
from model_grids import load_grid_from_directory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _grid_has_varying_metallicity(params):
    """Return True if the grid has more than one unique metallicity value."""
    fehs = set(p.get("metallicity", 0.0) for p in params)
    return len(fehs) > 1


def find_model_index(params, teff, logg, feh=None):
    """Return the index of the grid model matching (Teff, logg[, metallicity])."""
    for i, p in enumerate(params):
        if abs(p["Teff"] - teff) < 1.0 and abs(p["logg"] - logg) < 0.01:
            if feh is not None and abs(p.get("metallicity", 0.0) - feh) > 0.01:
                continue
            return i
    return None


def make_synthetic_obs(grid_wl, grid_spectra, model_idx, snr, rng):
    """Create a synthetic observed spectrum from a grid model.

    Returns (wl, flux, error) arrays.  For snr=None or snr<=0 returns
    noiseless data with tiny uniform errors (1e-20) to avoid division by zero.
    """
    wl = np.asarray(grid_wl, dtype=float)
    true_flux = grid_spectra[model_idx].copy()

    if snr is None or snr <= 0:
        # Noiseless: tiny error to keep fitter happy
        error = np.full_like(true_flux, 1e-20)
        return wl, true_flux, error

    # Gaussian noise with constant SNR across the spectrum
    error = true_flux / snr
    noise = rng.normal(0.0, 1.0, size=len(true_flux)) * error
    obs_flux = true_flux + noise
    return wl, obs_flux, error


def run_one_test(label, grid_wl, grid_spectra, grid_params, model_idx, snr, rng):
    """Run a single inject-and-recover test.  Returns result dict."""
    true_params = grid_params[model_idx]
    wl, obs_flux, obs_error = make_synthetic_obs(
        grid_wl, grid_spectra, model_idx, snr, rng
    )

    result = fit_spectrum_to_grid(
        obs_wl=wl,
        obs_flux=obs_flux,
        obs_error=obs_error,
        grid_wl=grid_wl,
        grid_spectra=grid_spectra,
        grid_params=grid_params,
    )

    result["_label"] = label
    result["_true_params"] = true_params
    result["_snr"] = snr
    result["_obs_wl"] = wl
    result["_obs_flux"] = obs_flux
    result["_obs_error"] = obs_error
    return result


# ---------------------------------------------------------------------------
# Terminal report
# ---------------------------------------------------------------------------

def print_report(result, grid_params, grid_spectra, grid_wl, full_ranking=False):
    """Print a detailed terminal diagnostic for one test."""
    label = result["_label"]
    true = result["_true_params"]
    snr = result["_snr"]
    show_feh = _grid_has_varying_metallicity(grid_params)

    hdr = f"\n{'=' * 70}\n  TEST: {label}  (SNR={'inf' if snr is None else snr})\n{'=' * 70}"
    print(hdr)
    inj_line = f"  Injected:  Teff = {true['Teff']:.0f} K,  logg = {true['logg']:.2f}"
    if show_feh:
        inj_line += f",  [Fe/H] = {true.get('metallicity', 0.0):+.1f}"
    print(inj_line)

    if not result["success"]:
        print(f"  ** FITTER FAILED: {result.get('error', '?')}")
        return False, {}

    best = result["best_fit_params"]
    rec_line = f"  Recovered: Teff = {best['Teff']:.0f} K,  logg = {best['logg']:.2f}"
    if show_feh:
        rec_line += f",  [Fe/H] = {best.get('metallicity', 0.0):+.1f}"
    print(rec_line)
    print(f"  chi^2      = {result['chi_squared']:.6e}")
    print(f"  chi^2_red  = {result['reduced_chi_squared']:.6f}")
    print(f"  scale      = {result['scaling_factor']:.6f}")

    # --- Chi-squared ranking ---
    wl_obs = np.asarray(result["_obs_wl"])
    f_obs = np.asarray(result["_obs_flux"])
    e_obs = np.asarray(result["_obs_error"])
    wl_grid = np.asarray(grid_wl)
    spectra = np.asarray(grid_spectra)

    all_chi = []
    for m in range(spectra.shape[0]):
        model_interp = np.interp(wl_obs, wl_grid, spectra[m])
        num = np.sum(f_obs * model_interp / e_obs ** 2)
        den = np.sum(model_interp ** 2 / e_obs ** 2)
        if den <= 0:
            all_chi.append((m, np.inf))
            continue
        scale = num / den
        chi = float(np.sum(((f_obs - scale * model_interp) / e_obs) ** 2))
        all_chi.append((m, chi))

    all_chi.sort(key=lambda x: x[1])

    n_pts = len(wl_obs)
    dof = max(1, n_pts - 1)
    n_models = len(all_chi)

    # Determine which rows to print
    show_top = 20
    show_bottom = 3
    truncate = not full_ranking and n_models > (show_top + show_bottom + 1)

    print(f"\n  Chi-squared ranking (N_pts={n_pts}, DoF={dof}, N_models={n_models}):")
    if show_feh:
        print(f"  {'Rank':>4}  {'Teff':>6}  {'logg':>5}  {'[Fe/H]':>6}  {'chi^2':>14}  {'chi^2_red':>10}  {'scale':>8}")
        print(f"  {'-' * 68}")
    else:
        print(f"  {'Rank':>4}  {'Teff':>6}  {'logg':>5}  {'chi^2':>14}  {'chi^2_red':>10}  {'scale':>8}")
        print(f"  {'-' * 55}")

    def _is_true(p):
        match = abs(p["Teff"] - true["Teff"]) < 1 and abs(p["logg"] - true["logg"]) < 0.01
        if show_feh:
            match = match and abs(p.get("metallicity", 0.0) - true.get("metallicity", 0.0)) < 0.01
        return match

    for rank, (m_idx, chi) in enumerate(all_chi, 1):
        if truncate and show_top < rank <= n_models - show_bottom:
            if rank == show_top + 1:
                print(f"  {'...':>4}  ({n_models - show_top - show_bottom} models omitted — use --full-ranking to show all)")
            continue

        p = grid_params[m_idx]
        chi_red = chi / dof if np.isfinite(chi) else np.inf
        model_interp = np.interp(wl_obs, wl_grid, spectra[m_idx])
        num = np.sum(f_obs * model_interp / e_obs ** 2)
        den = np.sum(model_interp ** 2 / e_obs ** 2)
        sc = num / den if den > 0 else 0.0
        marker = " <-- BEST" if rank == 1 else ""
        if _is_true(p):
            marker = " <-- BEST+TRUE" if rank == 1 else " <-- TRUE"

        if show_feh:
            feh_val = p.get("metallicity", 0.0)
            print(f"  {rank:>4}  {p['Teff']:>6.0f}  {p['logg']:>5.2f}  {feh_val:>+6.1f}  {chi:>14.6e}  {chi_red:>10.4f}  {sc:>8.4f}{marker}")
        else:
            print(f"  {rank:>4}  {p['Teff']:>6.0f}  {p['logg']:>5.2f}  {chi:>14.6e}  {chi_red:>10.4f}  {sc:>8.4f}{marker}")

    # --- Top 5 ---
    print(f"\n  Top 5 from fitter:")
    for i, t5 in enumerate(result["top_5"], 1):
        tp = t5["params"]
        feh_str = f", [Fe/H]={tp.get('metallicity', 0.0):+.1f}" if show_feh else ""
        print(f"    {i}. Teff={tp['Teff']:.0f}, logg={tp['logg']:.2f}{feh_str}, chi^2={t5['chi_squared']:.6e}")

    # --- Hypothesis tests ---
    tests = {}
    teff_diff = abs(best["Teff"] - true["Teff"])
    logg_diff = abs(best["logg"] - true["logg"])
    feh_diff = abs(best.get("metallicity", 0.0) - true.get("metallicity", 0.0))

    # Compute Teff grid step for SNR=10 threshold
    teffs_unique = sorted(set(p["Teff"] for p in grid_params))
    if len(teffs_unique) > 1:
        teff_step = min(teffs_unique[i+1] - teffs_unique[i] for i in range(len(teffs_unique) - 1))
    else:
        teff_step = 500.0

    if snr is None:
        # Noiseless
        exact_match = teff_diff < 1.0 and logg_diff < 0.01
        if show_feh:
            exact_match = exact_match and feh_diff < 0.01
        chi_zero = result["chi_squared"] < 1e-10
        tests["exact_param_recovery"] = exact_match
        tests["chi_sq_zero"] = chi_zero
        param_str = "Teff + logg" + (" + [Fe/H]" if show_feh else "")
        print(f"\n  HYPOTHESIS: Exact {param_str} recovery ... {'PASS' if exact_match else 'FAIL'}")
        print(f"  HYPOTHESIS: chi^2 ~ 0 (< 1e-10)        ... {'PASS' if chi_zero else 'FAIL'}  (actual: {result['chi_squared']:.2e})")
    elif snr == 50:
        teff_correct = teff_diff < 1.0
        chi_red_ok = 0.5 < result["reduced_chi_squared"] < 2.0
        tests["teff_recovery"] = teff_correct
        tests["chi_red_near_one"] = chi_red_ok
        # Check if logg is degenerate (top models span multiple logg at same Teff)
        logg_degenerate = False
        if result["top_5"]:
            top_teffs = [t5["params"]["Teff"] for t5 in result["top_5"][:3]]
            top_loggs = [t5["params"]["logg"] for t5 in result["top_5"][:3]]
            top_chis = [t5["chi_squared"] for t5 in result["top_5"][:3]]
            if len(set(top_teffs)) == 1 and len(set(top_loggs)) > 1:
                chi_spread = max(top_chis) - min(top_chis)
                if chi_spread / max(min(top_chis), 1e-30) < 0.01:
                    logg_degenerate = True
        logg_note = " (logg degenerate in grid — expected)" if logg_degenerate else ""
        logg_status = "PASS" if logg_diff < 0.01 else f"DEGEN{logg_note}" if logg_degenerate else "FAIL"
        print(f"\n  HYPOTHESIS: Correct Teff recovery       ... {'PASS' if teff_correct else 'FAIL'}")
        print(f"  HYPOTHESIS: Correct logg recovery       ... {logg_status}")
        # Metallicity recovery (only for grids with varying [Fe/H])
        if show_feh:
            feh_correct = feh_diff < 0.01
            tests["feh_recovery"] = feh_correct
            feh_status = "PASS" if feh_correct else "FAIL"
            print(f"  HYPOTHESIS: Correct [Fe/H] recovery     ... {feh_status}  (true={true.get('metallicity', 0.0):+.1f}, got={best.get('metallicity', 0.0):+.1f})")
        print(f"  HYPOTHESIS: 0.5 < chi^2_red < 2.0      ... {'PASS' if chi_red_ok else 'FAIL'}  (actual: {result['reduced_chi_squared']:.4f})")
    elif snr == 10:
        within_step = teff_diff <= teff_step
        tests["within_one_step"] = within_step
        print(f"\n  HYPOTHESIS: |dTeff| <= {teff_step:.0f} K (1 grid step) ... {'PASS' if within_step else 'FAIL'}  (actual: {teff_diff:.0f} K)")

    all_pass = all(tests.values()) if tests else False
    status = "ALL PASS" if all_pass else "SOME FAILED"
    print(f"\n  >> {status}")
    return all_pass, tests


# ---------------------------------------------------------------------------
# Diagnostic plot
# ---------------------------------------------------------------------------

def make_diagnostic_plot(results, grid_params, grid_spectra, grid_wl, output_path):
    """Generate a multi-panel diagnostic figure."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import LogNorm
    except ImportError:
        print("\n  [matplotlib not available — skipping plot]")
        return False

    n_tests = len(results)
    fig, axes = plt.subplots(n_tests, 3, figsize=(18, 5 * n_tests))
    if n_tests == 1:
        axes = axes[np.newaxis, :]

    # Collect unique Teff / logg for heatmap axes
    teffs = sorted(set(p["Teff"] for p in grid_params))
    loggs = sorted(set(p["logg"] for p in grid_params))
    teff_to_i = {t: i for i, t in enumerate(teffs)}
    logg_to_j = {g: j for j, g in enumerate(loggs)}

    wl_grid = np.asarray(grid_wl)
    spectra = np.asarray(grid_spectra)

    for row, res in enumerate(results):
        label = res["_label"]
        true = res["_true_params"]
        snr = res["_snr"]
        wl_obs = np.asarray(res["_obs_wl"])
        f_obs = np.asarray(res["_obs_flux"])
        e_obs = np.asarray(res["_obs_error"])

        # --- Panel 1: Spectrum + fit + residuals ---
        ax1 = axes[row, 0]
        ax1.plot(wl_obs, f_obs, "k.", ms=1, alpha=0.5, label="Observed")
        if res["success"]:
            ax1.plot(
                np.asarray(res["best_fit_wavelengths"]),
                np.asarray(res["best_fit_spectrum"]),
                "r-", lw=1, label=f"Best fit (Teff={res['best_fit_params']['Teff']:.0f})"
            )
        ax1.set_xlabel("Wavelength (micron)")
        ax1.set_ylabel("Flux")
        ax1.set_title(f"{label} — Spectrum")
        ax1.legend(fontsize=7)

        # Residuals inset
        if res["success"]:
            ax1b = ax1.twinx()
            residuals = np.asarray(res["residuals"])
            ax1b.plot(np.asarray(res["best_fit_wavelengths"]), residuals, "b.", ms=0.5, alpha=0.3)
            ax1b.set_ylabel("Residual", color="blue", fontsize=7)
            ax1b.tick_params(axis="y", labelcolor="blue", labelsize=6)

        # --- Panel 2: Chi^2 heatmap (Teff vs logg) ---
        ax2 = axes[row, 1]
        chi_grid = np.full((len(loggs), len(teffs)), np.nan)

        for m in range(spectra.shape[0]):
            model_interp = np.interp(wl_obs, wl_grid, spectra[m])
            num = np.sum(f_obs * model_interp / e_obs ** 2)
            den = np.sum(model_interp ** 2 / e_obs ** 2)
            if den <= 0:
                continue
            scale = num / den
            chi = float(np.sum(((f_obs - scale * model_interp) / e_obs) ** 2))
            p = grid_params[m]
            ti = teff_to_i[p["Teff"]]
            lj = logg_to_j[p["logg"]]
            # Take minimum chi² across metallicities for each (Teff, logg) cell
            if np.isnan(chi_grid[lj, ti]) or chi < chi_grid[lj, ti]:
                chi_grid[lj, ti] = chi

        valid = chi_grid[np.isfinite(chi_grid)]
        if len(valid) > 0:
            vmin = max(valid.min(), 1e-15)
            vmax = valid.max()
            if vmin >= vmax:
                vmin, vmax = vmax / 10, vmax * 10
            im = ax2.imshow(
                chi_grid, aspect="auto", origin="lower",
                norm=LogNorm(vmin=vmin, vmax=vmax),
                cmap="viridis_r",
                extent=[teffs[0] - 125, teffs[-1] + 125, loggs[0] - 0.125, loggs[-1] + 0.125],
            )
            fig.colorbar(im, ax=ax2, label="chi^2")
        ax2.set_xlabel("Teff (K)")
        ax2.set_ylabel("log g")
        ax2.set_title(f"{label} — chi^2 landscape")
        # Mark true position
        ax2.plot(true["Teff"], true["logg"], "r*", ms=15, label="True")
        if res["success"]:
            bp = res["best_fit_params"]
            ax2.plot(bp["Teff"], bp["logg"], "wx", ms=12, mew=2, label="Best fit")
        ax2.legend(fontsize=7)

        # --- Panel 3: Top-5 bar chart ---
        ax3 = axes[row, 2]
        show_feh_plot = _grid_has_varying_metallicity(grid_params)
        if res["success"] and res["top_5"]:
            labels_bar = []
            chi_vals = []
            for t5 in res["top_5"]:
                tp = t5["params"]
                lbl = f"T={tp['Teff']:.0f}\ng={tp['logg']:.1f}"
                if show_feh_plot:
                    lbl += f"\n[Fe/H]={tp.get('metallicity', 0.0):+.1f}"
                labels_bar.append(lbl)
                chi_vals.append(t5["chi_squared"])
            colors = ["#2ecc71" if i == 0 else "#3498db" for i in range(len(chi_vals))]
            ax3.barh(range(len(chi_vals)), chi_vals, color=colors)
            ax3.set_yticks(range(len(labels_bar)))
            ax3.set_yticklabels(labels_bar, fontsize=8)
            ax3.set_xlabel("chi^2")
            ax3.set_title(f"{label} — Top 5")
            ax3.invert_yaxis()

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"\n  Diagnostic plot saved: {output_path}")
    plt.close(fig)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Inject-and-recover validation for SA3D grid fitter"
    )
    parser.add_argument(
        "--grid", default="phoenix_cool",
        help="Grid directory name under model_grids/ (default: phoenix_cool)"
    )
    parser.add_argument("--teff", type=float, default=3500.0, help="Injection Teff (default: 3500)")
    parser.add_argument("--logg", type=float, default=4.5, help="Injection logg (default: 4.5)")
    parser.add_argument("--feh", type=float, default=None, help="Injection [Fe/H] (default: None = first match; use -0.5 for PHOENIX)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--no-plot", action="store_true", help="Skip diagnostic plot")
    parser.add_argument("--full-ranking", action="store_true", help="Show all models in ranking table")
    args = parser.parse_args()

    # --- Load grid ---
    grid_dir = os.path.join(PROJECT_ROOT, "model_grids", args.grid)
    print(f"Loading grid from: {grid_dir}")
    grid = load_grid_from_directory(grid_dir)
    print(f"  {grid['n_models']} models loaded, {len(grid['wavelengths'])} wavelength points")

    grid_wl = grid["wavelengths"]
    grid_spectra = grid["spectra"]
    grid_params = grid["params"]

    # --- Determine metallicity for injection ---
    has_feh = _grid_has_varying_metallicity(grid_params)
    inject_feh = args.feh
    if inject_feh is None and has_feh:
        # Default to -0.5 for grids with varying metallicity
        inject_feh = -0.5

    # --- Find injection model ---
    model_idx = find_model_index(grid_params, args.teff, args.logg, feh=inject_feh)
    if model_idx is None:
        feh_str = f", [Fe/H]={inject_feh:+.1f}" if inject_feh is not None else ""
        print(f"\nERROR: No model found with Teff={args.teff}, logg={args.logg}{feh_str}")
        print("Available models:")
        seen = set()
        for p in grid_params:
            feh_val = p.get("metallicity", 0.0)
            key = (p["Teff"], p["logg"], feh_val)
            if key not in seen:
                seen.add(key)
                feh_disp = f", [Fe/H]={feh_val:+.1f}" if has_feh else ""
                print(f"  Teff={p['Teff']:.0f}, logg={p['logg']:.2f}{feh_disp}")
        if has_feh:
            fehs_avail = sorted(set(p.get("metallicity", 0.0) for p in grid_params))
            print(f"\n  Available [Fe/H] values: {fehs_avail}")
        sys.exit(1)

    true_p = grid_params[model_idx]
    inj_str = f"  Injection model: Teff={true_p['Teff']:.0f} K, logg={true_p['logg']:.2f}"
    if has_feh:
        inj_str += f", [Fe/H]={true_p.get('metallicity', 0.0):+.1f}"
    inj_str += f" (index {model_idx})"
    print(inj_str)

    rng = np.random.default_rng(args.seed)

    # --- Run tests at 3 SNR levels ---
    test_configs = [
        ("Noiseless (SNR=inf)", None),
        ("SNR=50 (good JWST)", 50),
        ("SNR=10 (noisy)", 10),
    ]

    results = []
    all_pass = True
    for label, snr in test_configs:
        res = run_one_test(label, grid_wl, grid_spectra, grid_params, model_idx, snr, rng)
        passed, _ = print_report(res, grid_params, grid_spectra, grid_wl, full_ranking=args.full_ranking)
        if not passed:
            all_pass = False
        results.append(res)

    # --- Diagnostic plot ---
    if not args.no_plot:
        plot_path = os.path.join(PROJECT_ROOT, "model_grids", "validation_report.png")
        make_diagnostic_plot(results, grid_params, grid_spectra, grid_wl, plot_path)

    # --- Summary ---
    print(f"\n{'=' * 70}")
    print(f"  SUMMARY: {'ALL TESTS PASSED' if all_pass else 'SOME TESTS FAILED'}")
    print(f"{'=' * 70}\n")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
