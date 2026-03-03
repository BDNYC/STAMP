from astropy.io import fits
import numpy as np
from astropy.time import Time

fits_file = '/Users/anthonymunozperez/Desktop/JWST/jw01647-o001_t001_nirspec_clear-prism-s1600a1-sub512_x1dints.fits'

print("=" * 80)
print("COMPREHENSIVE FITS FILE DIAGNOSIS")
print("=" * 80)

with fits.open(fits_file) as hdul:
    print("\n" + "=" * 80)
    print("1. FILE STRUCTURE")
    print("=" * 80)
    hdul.info()

    print(f"\nTotal HDUs: {len(hdul)}")
    print(f"HDU Names: {[hdu.name for hdu in hdul]}")

    print("\n" + "=" * 80)
    print("2. INT_TIMES EXTENSION - DETAILED")
    print("=" * 80)

    if 'INT_TIMES' not in hdul:
        print("CRITICAL: NO INT_TIMES EXTENSION FOUND")
        exit(1)

    int_times = hdul['INT_TIMES'].data
    print(f"INT_TIMES found")
    print(f"Number of entries: {len(int_times)}")
    print(f"Columns: {int_times.columns.names}")
    print(f"\nColumn data types:")
    for col in int_times.columns:
        print(f"  {col.name}: {col.format}")

    mjd_col = 'int_mid_MJD_UTC'
    if mjd_col in int_times.columns.names:
        mjd_values = int_times[mjd_col]
        print(f"\n{mjd_col} statistics:")
        print(f"  Length: {len(mjd_values)}")
        print(f"  Min:  {np.min(mjd_values):.10f}")
        print(f"  Max: {np.max(mjd_values):.10f}")
        print(f"  Range: {np.max(mjd_values) - np.min(mjd_values):.10f} days")
        print(f"  Range in hours: {(np.max(mjd_values) - np.min(mjd_values)) * 24:.4f}")
        print(f"  First 10 values:")
        for i in range(min(10, len(mjd_values))):
            print(f"    [{i}] {mjd_values[i]:.10f}")

    print("\n" + "=" * 80)
    print("3. EXTRACT1D EXTENSION - COMPREHENSIVE ANALYSIS")
    print("=" * 80)

    if 'EXTRACT1D' not in hdul:
        print("CRITICAL: NO EXTRACT1D EXTENSION FOUND")
        exit(1)

    extract = hdul['EXTRACT1D']
    print(f"EXTRACT1D found")
    print(f"Extension class: {extract.__class__.__name__}")
    print(f"Data type:  {type(extract.data)}")
    print(f"Data class: {extract.data.__class__.__name__}")

    # Check if it's a table
    is_table = hasattr(extract.data, 'columns')
    print(f"\nIs table format: {is_table}")

    if is_table:
        print(f"Number of rows: {len(extract.data)}")
        print(f"Number of columns: {len(extract.data.columns)}")
        print(f"\nAll columns:  {extract.data.columns.names}")

        print(f"\nColumn data types:")
        for col in extract.data.columns:
            print(f"  {col.name}: {col.format}")

        print("\n" + "-" * 80)
        print("3a. TIME COLUMNS IN EXTRACT1D")
        print("-" * 80)

        time_cols = [col for col in extract.data.columns.names
                     if any(x in col for x in ['MJD', 'TIME', 'BJD', 'TDB'])]
        print(f"Time-related columns found: {time_cols}")

        if time_cols:
            for col_name in time_cols:
                col_data = extract.data[col_name]
                print(f"\n{col_name}:")
                print(f"  Length: {len(col_data)}")
                print(f"  Data type: {col_data.dtype}")
                print(f"  Shape: {col_data.shape}")
                print(f"  Min: {np.min(col_data):.10f}")
                print(f"  Max: {np.max(col_data):.10f}")
                print(f"  First 5 values:  {col_data[: 5]}")

                # Check if times match INT_TIMES
                if len(col_data) == len(int_times):
                    if 'AVG' in col_name or 'mid' in col_name.lower():
                        diff = np.abs(col_data - int_times[mjd_col])
                        print(f"  Match with INT_TIMES: max difference = {np.max(diff):.2e} days")
        else:
            print("NO TIME COLUMNS IN EXTRACT1D TABLE")

        print("\n" + "-" * 80)
        print("3b. WAVELENGTH DATA")
        print("-" * 80)

        if 'WAVELENGTH' not in extract.data.columns.names:
            print("CRITICAL: NO WAVELENGTH COLUMN")
        else:
            wl_data = extract.data['WAVELENGTH']
            print(f"WAVELENGTH column found")
            print(f"Column shape: {wl_data.shape}")
            print(f"Data type: {wl_data.dtype}")

            print(f"\nFirst row wavelength array:")
            first_wl = wl_data[0]
            print(f"  Shape: {first_wl.shape}")
            print(f"  Length: {len(first_wl)}")
            print(f"  Min: {np.nanmin(first_wl):.6f}")
            print(f"  Max: {np.nanmax(first_wl):.6f}")
            print(f"  First 10 values: {first_wl[:10]}")
            print(f"  Number of NaN:  {np.sum(np.isnan(first_wl))}")
            print(f"  Number of Inf: {np.sum(np.isinf(first_wl))}")
            print(f"  Number of finite:  {np.sum(np.isfinite(first_wl))}")

            # Check if wavelength is same for all rows
            if len(wl_data) > 1:
                last_wl = wl_data[-1]
                if np.allclose(first_wl, last_wl, equal_nan=True):
                    print(f"  Wavelength array is same for all rows")
                else:
                    print(f"  Wavelength varies between rows")

        print("\n" + "-" * 80)
        print("3c. FLUX DATA - DETAILED ANALYSIS")
        print("-" * 80)

        if 'FLUX' not in extract.data.columns.names:
            print("CRITICAL: NO FLUX COLUMN")
        else:
            flux_data = extract.data['FLUX']
            print(f"FLUX column found")
            print(f"Column shape: {flux_data.shape}")
            print(f"Data type: {flux_data.dtype}")

            print(f"\nAnalyzing FLUX data across ALL integrations:")

            # Statistics for each integration
            all_nan_count = 0
            all_finite_count = 0
            partial_nan_count = 0

            for i in range(len(flux_data)):
                flux_row = flux_data[i]
                n_finite = np.sum(np.isfinite(flux_row))
                n_nan = np.sum(np.isnan(flux_row))
                n_inf = np.sum(np.isinf(flux_row))

                if n_finite == 0:
                    all_nan_count += 1
                elif n_finite == len(flux_row):
                    all_finite_count += 1
                else:
                    partial_nan_count += 1

                # Print first 10 rows in detail
                if i < 10:
                    print(f"\n  Row {i}:")
                    print(f"    Shape: {flux_row.shape}")
                    print(f"    Finite values: {n_finite}/{len(flux_row)}")
                    print(f"    NaN values: {n_nan}")
                    print(f"    Inf values: {n_inf}")
                    if n_finite > 0:
                        finite_vals = flux_row[np.isfinite(flux_row)]
                        print(f"    Min (finite): {np.min(finite_vals):.6e}")
                        print(f"    Max (finite): {np.max(finite_vals):.6e}")
                        print(f"    Mean (finite): {np.mean(finite_vals):.6e}")
                        print(f"    First 10 values: {flux_row[:10]}")
                    else:
                        print(f"    ALL VALUES ARE NaN/Inf")
                        print(f"    First 10 values: {flux_row[:10]}")

            print(f"\n  SUMMARY across {len(flux_data)} integrations:")
            print(f"    Integrations with ALL finite values: {all_finite_count}")
            print(f"    Integrations with SOME finite values: {partial_nan_count}")
            print(f"    Integrations with NO finite values: {all_nan_count}")

            if all_nan_count == len(flux_data):
                print(f"\n  CRITICAL: ALL INTEGRATIONS HAVE NO VALID FLUX DATA")
            elif all_nan_count > len(flux_data) * 0.5:
                print(f"\n  WARNING: More than 50% of integrations have no valid data")
            else:
                print(f"\n  Sufficient valid flux data found")

        print("\n" + "-" * 80)
        print("3d. ERROR DATA")
        print("-" * 80)

        if 'FLUX_ERROR' in extract.data.columns.names:
            err_data = extract.data['FLUX_ERROR']
            print(f"FLUX_ERROR column found")
            print(f"Shape: {err_data.shape}")

            # Check first row
            first_err = err_data[0]
            n_finite_err = np.sum(np.isfinite(first_err))
            print(f"First row:  {n_finite_err}/{len(first_err)} finite error values")
            if n_finite_err > 0:
                finite_err = first_err[np.isfinite(first_err)]
                print(f"  Error range: {np.min(finite_err):.6e} to {np.max(finite_err):.6e}")
        else:
            print("No FLUX_ERROR column")

    print("\n" + "=" * 80)
    print("4. CHECKING FOR INDIVIDUAL EXTRACT1D EXTENSIONS")
    print("=" * 80)

    has_individual = False
    try:
        test_ext = hdul['EXTRACT1D', 1]
        has_individual = True
        print(f"Found individual extension: ('EXTRACT1D', 1)")
        print(f"  Type: {type(test_ext)}")
        if hasattr(test_ext.data, 'columns'):
            print(f"  Columns:  {test_ext.data.columns.names}")

            # Check flux in individual extension
            if 'FLUX' in test_ext.data.columns.names:
                ind_flux = test_ext.data['FLUX']
                print(f"  FLUX shape: {ind_flux.shape}")
                print(f"  Finite values: {np.sum(np.isfinite(ind_flux))}/{len(ind_flux)}")
    except (KeyError, IndexError, TypeError) as e:
        print(f"No individual extensions found (this is OK): {type(e).__name__}")

    print("\n" + "=" * 80)
    print("5. PRIMARY HEADER INFORMATION")
    print("=" * 80)

    primary = hdul[0].header
    important_keys = ['TARGNAME', 'INSTRUME', 'FILTER', 'GRATING', 'DATE-OBS',
                      'EXPTIME', 'BUNIT', 'TELESCOP', 'NINTS']

    for key in important_keys:
        if key in primary:
            print(f"{key}: {primary[key]}")

    print("\n" + "=" * 80)
    print("6. FINAL DIAGNOSIS")
    print("=" * 80)

    if 'INT_TIMES' in hdul and 'EXTRACT1D' in hdul:
        n_times = len(hdul['INT_TIMES'].data)
        n_extract = len(hdul['EXTRACT1D'].data) if hasattr(hdul['EXTRACT1D'].data, '__len__') else 0

        print(f"INT_TIMES entries: {n_times}")
        print(f"EXTRACT1D rows: {n_extract}")

        if n_times == n_extract:
            print("Counts match")
        else:
            print("Count mismatch")

        # Determine expected code path
        if is_table and time_cols:
            print("\nEXPECTED CODE PATH:  Table format with embedded time columns")
            print(
                f"  Should use time column: {time_cols[0] if 'AVG' in time_cols[0] or 'mid' in time_cols[0].lower() else time_cols[0]}")
        elif has_individual:
            print("\nEXPECTED CODE PATH:  Individual EXTRACT1D extensions")
            print(f"  Should iterate through ('EXTRACT1D', 1) to ('EXTRACT1D', {n_times})")
        elif is_table and not time_cols:
            print("\nEXPECTED CODE PATH:  Table format using INT_TIMES for time")
            print(f"  Should use INT_TIMES[{mjd_col}] for time values")
        else:
            print("\nUNKNOWN FORMAT")

print("\n" + "=" * 80)
print("DIAGNOSIS COMPLETE")
print("=" * 80)