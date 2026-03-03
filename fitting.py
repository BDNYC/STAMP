"""Pure model-fitting math for STAMP spectral time-series data.

No Flask, no Plotly — just numpy/scipy functions that take arrays and return dicts.
"""

import numpy as np
from scipy.optimize import curve_fit


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
            "amplitudes": amplitudes.tolist(),
            "periods": periods.tolist(),
            "phases": phases.tolist(),
            "chi_squared": chi_sq.tolist(),
            "success_mask": success_mask.tolist(),
            "n_sines": n_sines,
        }

    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _quality_note(reduced_chi_sq, n_points, median_snr):
    """Return a human-readable interpretation of the reduced chi-squared value."""
    if reduced_chi_sq < 2.0:
        return "Good fit"
    elif reduced_chi_sq < 10.0:
        return "Moderate — model captures overall shape but misses fine features"
    elif median_snr > 50:
        return ("High — likely underestimated errors or missing model physics "
                "(common with JWST pipeline uncertainties)")
    else:
        return "High — may be low SNR data or model mismatch"


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

        if len(wl_obs) < 5:
            return {"success": False, "error": "Not enough valid data points"}

        wl_grid = np.asarray(grid_wl, dtype=float)
        spectra = np.asarray(grid_spectra, dtype=float)  # (N_models, W_grid)
        n_models = spectra.shape[0]

        best_chi = np.inf
        best_idx = -1
        best_scale = 1.0
        all_chi = np.full(n_models, np.inf)

        for m in range(n_models):
            # Interpolate model onto observed wavelength grid
            model_interp = np.interp(wl_obs, wl_grid, spectra[m])

            # Optimal scaling factor
            num = np.sum(f_obs * model_interp / e_obs ** 2)
            den = np.sum(model_interp ** 2 / e_obs ** 2)
            if den <= 0:
                continue
            scale = num / den
            scaled = scale * model_interp
            chi = float(np.sum(((f_obs - scaled) / e_obs) ** 2))
            all_chi[m] = chi

            if chi < best_chi:
                best_chi = chi
                best_idx = m
                best_scale = scale

        if best_idx < 0:
            return {"success": False, "error": "No valid model fits found"}

        # Get best fit spectrum on observed grid
        best_model = np.interp(wl_obs, wl_grid, spectra[best_idx])
        best_fit = best_scale * best_model
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

        # Check if best-fit Teff is at the grid boundary
        warnings = []
        best_params = grid_params[best_idx] if best_idx < len(grid_params) else {}
        if best_params and "Teff" in best_params:
            all_teffs = [p["Teff"] for p in grid_params if "Teff" in p]
            if all_teffs:
                grid_teff_min = min(all_teffs)
                grid_teff_max = max(all_teffs)
                if best_params["Teff"] <= grid_teff_min:
                    warnings.append(
                        f"Best-fit Teff ({best_params['Teff']:.0f} K) is at the grid "
                        f"lower boundary — true Teff may be below {grid_teff_min:.0f} K. "
                        f"Consider using a grid with cooler models."
                    )
                elif best_params["Teff"] >= grid_teff_max:
                    warnings.append(
                        f"Best-fit Teff ({best_params['Teff']:.0f} K) is at the grid "
                        f"upper boundary — true Teff may be above {grid_teff_max:.0f} K. "
                        f"Consider using a grid with hotter models."
                    )

        reduced_chi_sq = float(best_chi / max(1, len(wl_obs) - 1))
        median_snr = float(np.median(f_obs / e_obs))

        result = {
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
            "quality_note": _quality_note(reduced_chi_sq, len(wl_obs), median_snr),
        }
        if warnings:
            result["warnings"] = warnings
        return result

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
            "chi_squared": chi_squared.tolist(),
            "scaling_factors": scaling_factors.tolist(),
            "success_mask": success_mask.tolist(),
        }

    except Exception as exc:
        return {"success": False, "error": str(exc)}
