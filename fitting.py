"""Pure model-fitting math for STAMP spectral time-series data.

No Flask, no Plotly — just numpy/scipy functions that take arrays and return dicts.
"""

import numpy as np
from scipy.optimize import curve_fit


def _nan_to_none(arr):
    """Convert a numpy array to a list, replacing NaN with None for JSON safety."""
    return [None if np.isnan(v) else v for v in arr.ravel()]


def _nan_to_none_2d(arr):
    """Convert a 2D numpy array to nested lists, replacing NaN with None."""
    return [[None if np.isnan(v) else v for v in row] for row in arr]


def _sine_model(t, *params):
    """Multi-sine function: offset + sum(A_i * sin(2*pi*t/P_i + phi_i)).

    Parameters are packed as: [offset, A_0, P_0, phi_0, A_1, P_1, phi_1, ...]
    """
    offset = params[0]
    result = np.full_like(t, offset, dtype=float)
    n_sines = (len(params) - 1) // 3
    for i in range(n_sines):
        amp = params[1 + 3 * i]
        period = params[2 + 3 * i]
        phase = params[3 + 3 * i]
        result += amp * np.sin(2.0 * np.pi * t / period + phase)
    return result


def fit_sinusoidal(time_arr, flux_arr, error_arr=None, n_sines=1, period_guess=None):
    """Fit a multi-sine model to a 1D light curve.

    Returns dict with keys: success, fit_values, params, offset, residuals,
    chi_squared, reduced_chi_squared.
    """
    try:
        t = np.asarray(time_arr, dtype=float)
        f = np.asarray(flux_arr, dtype=float)

        mask = np.isfinite(t) & np.isfinite(f)
        if error_arr is not None:
            e = np.asarray(error_arr, dtype=float)
            mask &= np.isfinite(e) & (e > 0)
            e = e[mask]
        else:
            e = None
        t = t[mask]
        f = f[mask]

        if len(t) < (1 + 3 * n_sines + 1):
            return {"success": False, "error": "Not enough valid data points"}

        # Initial guesses
        offset_guess = float(np.nanmedian(f))
        t_range = float(t.max() - t.min()) if len(t) > 1 else 1.0
        amp_guess = float(np.nanstd(f))
        if period_guess is None:
            period_guess = t_range / 2.0

        p0 = [offset_guess]
        lower = [offset_guess - 10 * amp_guess]
        upper = [offset_guess + 10 * amp_guess]
        for i in range(n_sines):
            p_g = period_guess / (i + 1)
            p0.extend([amp_guess, p_g, 0.0])
            lower.extend([0.0, t_range / len(t), -2 * np.pi])
            upper.extend([10 * amp_guess, t_range * 2, 2 * np.pi])

        popt, _ = curve_fit(
            _sine_model, t, f, p0=p0,
            sigma=e, absolute_sigma=(e is not None),
            bounds=(lower, upper),
            maxfev=10000,
        )

        fit_values = _sine_model(t, *popt)
        residuals = f - fit_values

        if e is not None:
            chi_sq = float(np.sum((residuals / e) ** 2))
        else:
            chi_sq = float(np.sum(residuals ** 2))

        dof = max(1, len(t) - len(popt))
        reduced_chi_sq = chi_sq / dof

        params_list = []
        for i in range(n_sines):
            params_list.append({
                "amplitude": float(popt[1 + 3 * i]),
                "period": float(popt[2 + 3 * i]),
                "phase": float(popt[3 + 3 * i]),
            })

        # Compute fit over the full (unmasked) input for overlay
        t_full = np.asarray(time_arr, dtype=float)
        fit_full = _sine_model(t_full, *popt)

        return {
            "success": True,
            "fit_values": fit_full.tolist(),
            "fit_time": t_full.tolist(),
            "params": params_list,
            "offset": float(popt[0]),
            "residuals": residuals.tolist(),
            "residual_time": t.tolist(),
            "chi_squared": chi_sq,
            "reduced_chi_squared": reduced_chi_sq,
        }

    except Exception as exc:
        return {"success": False, "error": str(exc)}


def fit_sinusoidal_all_wavelengths(wavelength_arr, time_arr, flux_2d, error_2d=None,
                                   n_sines=1, period_guess=None, progress_cb=None):
    """Fit sinusoidal model to each wavelength slice, sweeping amplitude vs wavelength.

    flux_2d shape: (n_wavelengths, n_times)
    Returns dict with wavelengths, amplitudes, periods, phases, chi_squared, success_mask.
    """
    try:
        wl = np.asarray(wavelength_arr, dtype=float)
        t = np.asarray(time_arr, dtype=float)
        flux = np.asarray(flux_2d, dtype=float)
        err = np.asarray(error_2d, dtype=float) if error_2d is not None else None

        n_wl = len(wl)
        amplitudes = np.full((n_wl, n_sines), np.nan)
        periods = np.full((n_wl, n_sines), np.nan)
        phases = np.full((n_wl, n_sines), np.nan)
        chi_sq = np.full(n_wl, np.nan)
        success_mask = np.zeros(n_wl, dtype=bool)

        for i in range(n_wl):
            e_row = err[i] if err is not None else None
            result = fit_sinusoidal(t, flux[i], e_row, n_sines=n_sines, period_guess=period_guess)
            if result["success"]:
                success_mask[i] = True
                chi_sq[i] = result["chi_squared"]
                for j, p in enumerate(result["params"]):
                    amplitudes[i, j] = p["amplitude"]
                    periods[i, j] = p["period"]
                    phases[i, j] = p["phase"]
            if progress_cb and i % max(1, n_wl // 20) == 0:
                progress_cb(float(i) / n_wl * 100.0)

        return {
            "success": True,
            "wavelengths": wl.tolist(),
            "amplitudes": _nan_to_none_2d(amplitudes),
            "periods": _nan_to_none_2d(periods),
            "phases": _nan_to_none_2d(phases),
            "chi_squared": _nan_to_none(chi_sq),
            "success_mask": success_mask.tolist(),
            "n_sines": n_sines,
        }

    except Exception as exc:
        return {"success": False, "error": str(exc)}


def fit_spectrum_to_grid(obs_wl, obs_flux, obs_error, grid_wl, grid_spectra, grid_params):
    """Fit an observed spectrum against a model grid using chi-squared minimization.

    Optimal scaling: scale = sum(f*m/e^2) / sum(m^2/e^2)
    Returns dict with best_fit_params, best_fit_spectrum, residuals, chi_squared, etc.
    """
    try:
        wl_obs = np.asarray(obs_wl, dtype=float)
        f_obs = np.asarray(obs_flux, dtype=float)
        e_obs = np.asarray(obs_error, dtype=float)

        mask = np.isfinite(wl_obs) & np.isfinite(f_obs) & np.isfinite(e_obs) & (e_obs > 0)
        wl_obs = wl_obs[mask]
        f_obs = f_obs[mask]
        e_obs = e_obs[mask]

        wl_grid = np.asarray(grid_wl, dtype=float)

        # Restrict to wavelengths covered by the model grid (avoid silent extrapolation)
        grid_coverage = (wl_obs >= wl_grid[0]) & (wl_obs <= wl_grid[-1])
        wl_obs = wl_obs[grid_coverage]
        f_obs = f_obs[grid_coverage]
        e_obs = e_obs[grid_coverage]

        if len(wl_obs) < 5:
            return {"success": False, "error": "Not enough valid data points"}

        spectra = np.asarray(grid_spectra, dtype=float)  # (N_models, W_grid)
        n_models = spectra.shape[0]

        # Batch-interpolate all models onto observed wavelength grid
        models_interp = np.array([
            np.interp(wl_obs, wl_grid, spectra[m])
            for m in range(n_models)
        ])  # shape: (n_models, n_obs)

        # Compute optimal scaling factors for all models at once
        inv_var = 1.0 / e_obs**2                          # (n_obs,)
        num = models_interp @ (f_obs * inv_var)            # (n_models,)
        den = models_interp**2 @ inv_var                   # (n_models,)

        valid = (den > 0) & (num > 0)
        scales = np.where(valid, num / den, 0.0)           # (n_models,)

        # Compute chi-squared for all models at once
        scaled_models = scales[:, None] * models_interp    # (n_models, n_obs)
        residuals_all = f_obs[None, :] - scaled_models     # (n_models, n_obs)
        all_chi = np.sum((residuals_all / e_obs[None, :])**2, axis=1)  # (n_models,)
        all_chi[~valid] = np.inf

        best_idx = int(np.argmin(all_chi))
        best_chi = float(all_chi[best_idx])
        best_scale = float(scales[best_idx])

        if not np.isfinite(best_chi):
            return {"success": False, "error": "No valid model fits found"}

        # Get best fit spectrum on observed grid
        best_fit = best_scale * models_interp[best_idx]
        residuals = f_obs - best_fit

        # Top 5 by chi-squared
        sorted_idx = np.argsort(all_chi)[:5]
        top_5 = []
        for idx in sorted_idx:
            if np.isfinite(all_chi[idx]):
                top_5.append({
                    "params": grid_params[idx] if idx < len(grid_params) else {},
                    "chi_squared": float(all_chi[idx]),
                })

        best_params = grid_params[best_idx] if best_idx < len(grid_params) else {}

        reduced_chi_sq = float(best_chi / max(1, len(wl_obs) - 1))
        median_snr = float(np.median(np.abs(f_obs) / e_obs))

        return {
            "success": True,
            "best_fit_params": best_params,
            "best_fit_spectrum": best_fit.tolist(),
            "best_fit_wavelengths": wl_obs.tolist(),
            "residuals": residuals.tolist(),
            "chi_squared": float(best_chi),
            "reduced_chi_squared": reduced_chi_sq,
            "scaling_factor": float(best_scale),
            "top_5": top_5,
            "n_data_points": len(wl_obs),
            "median_snr": median_snr,
        }

    except Exception as exc:
        return {"success": False, "error": str(exc)}


def fit_spectrum_chunked(obs_wl, obs_flux, obs_error, grid_wl, grid_spectra, grid_params, chunks):
    """Fit observed spectrum in wavelength chunks against a model grid.

    Each chunk defines a wavelength range; data is masked to that range and
    fit_spectrum_to_grid is called independently per chunk.

    Parameters
    ----------
    obs_wl, obs_flux, obs_error : array-like
        Observed wavelengths, flux, and errors.
    grid_wl, grid_spectra, grid_params : array-like / list
        Model grid data (passed through to fit_spectrum_to_grid).
    chunks : list of dict
        Each dict has 'min' and 'max' keys (wavelength bounds).

    Returns
    -------
    dict with 'success' and 'chunk_results' (list of per-chunk result dicts).
    """
    try:
        wl = np.asarray(obs_wl, dtype=float)
        flux = np.asarray(obs_flux, dtype=float)
        error = np.asarray(obs_error, dtype=float)

        chunk_results = []
        for chunk in chunks:
            wl_min = float(chunk['min'])
            wl_max = float(chunk['max'])
            mask = (wl >= wl_min) & (wl <= wl_max)

            if np.sum(mask) < 5:
                chunk_results.append({
                    "success": False,
                    "error": f"Chunk [{wl_min:.4f}, {wl_max:.4f}] has fewer than 5 data points",
                    "_wl_min": wl_min,
                    "_wl_max": wl_max,
                })
                continue

            result = fit_spectrum_to_grid(
                wl[mask], flux[mask], error[mask],
                grid_wl, grid_spectra, grid_params,
            )
            result['_wl_min'] = wl_min
            result['_wl_max'] = wl_max
            chunk_results.append(result)

        return {"success": True, "chunk_results": chunk_results}

    except Exception as exc:
        return {"success": False, "error": str(exc)}


def fit_spectrum_all_timesteps(wavelength_arr, time_arr, flux_2d, error_2d,
                               grid_wl, grid_spectra, grid_params, progress_cb=None):
    """Fit each time-step spectrum against a model grid.

    flux_2d shape: (n_wavelengths, n_times)
    Returns dict with times, best_params, chi_squared, scaling_factors, success_mask.
    """
    try:
        wl = np.asarray(wavelength_arr, dtype=float)
        t = np.asarray(time_arr, dtype=float)
        flux = np.asarray(flux_2d, dtype=float)
        err = np.asarray(error_2d, dtype=float)

        n_times = len(t)
        best_params = []
        chi_squared = np.full(n_times, np.nan)
        scaling_factors = np.full(n_times, np.nan)
        success_mask = np.zeros(n_times, dtype=bool)

        for j in range(n_times):
            f_col = flux[:, j]
            e_col = err[:, j]
            result = fit_spectrum_to_grid(wl, f_col, e_col, grid_wl, grid_spectra, grid_params)
            if result["success"]:
                success_mask[j] = True
                best_params.append(result["best_fit_params"])
                chi_squared[j] = result["chi_squared"]
                scaling_factors[j] = result["scaling_factor"]
            else:
                best_params.append({})
            if progress_cb and j % max(1, n_times // 20) == 0:
                progress_cb(float(j) / n_times * 100.0)

        return {
            "success": True,
            "times": t.tolist(),
            "best_params": best_params,
            "chi_squared": _nan_to_none(chi_squared),
            "scaling_factors": _nan_to_none(scaling_factors),
            "success_mask": success_mask.tolist(),
        }

    except Exception as exc:
        return {"success": False, "error": str(exc)}
