# STAMP: Spectral Time-series Analysis and Mapping Program

STAMP is a browser-based tool for exploring JWST spectral time-series observations. It ingests FITS `x1dints` files or HDF5 spectral cubes from MAST, generates interactive 3D surface plots and 2D heatmaps, and fits model atmosphere grids to individual or time-resolved spectra. Designed for brown dwarf and exoplanet atmosphere characterization, it runs as a Flask web application with Plotly visualizations.

## Demo

https://github.com/user-attachments/assets/5a01ca58-5b0d-4078-a50f-9c2a2068db7f

## Features

- **MAST data ingestion** — Query and download JWST spectral time-series directly from MAST, or upload local FITS/HDF5 files
- **Interactive 3D surface plots** — Flux vs. wavelength vs. time rendered as rotatable Plotly surfaces
- **2D heatmaps** — Wavelength-time heatmaps with configurable color scales
- **Spectral band filtering** — Restrict wavelength, time, and variability ranges interactively
- **Time-series video generation** — Animate spectra frame-by-frame as MP4 (requires ffmpeg)
- **Model atmosphere fitting** — Chi-squared grid fitting against 12 synthetic spectral libraries (see [Model Grids](#model-grids))
- **Chunked spectral fitting** — Fit independent wavelength segments to detect spatially-varying atmospheric properties
- **Parameter sweeps** — Fit all time-steps against a grid to track Teff, log g, and metallicity evolution
- **Sinusoidal light-curve fitting** — Fit single or multi-component sinusoids to extracted light curves, with amplitude-vs-wavelength sweeps
- **Data export** — Download standalone HTML plots, CSV tables, and combined ZIP archives with embedded video
- **Interactive guided tour** — Step-by-step walkthrough of the interface for new users

## Live Instance

[https://stamp.us.reclaim.cloud](https://stamp.us.reclaim.cloud)

## Quick Start

```bash
git clone https://github.com/munozcar/SA3D.git
cd SA3D
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Download at least one model grid (optional, for fitting)
python scripts/download_all_grids.py

# Run the development server
python app.py
```

The app will be available at `http://localhost:5000`.

For production deployment, use gunicorn:

```bash
gunicorn wsgi:application --bind 0.0.0.0:8080
```

## Supported Data Formats

### FITS (JWST x1dints)

STAMP reads multi-integration JWST spectral files (`_x1dints.fits`). Each file must contain:

- One or more `EXTRACT1D` HDUs with columns `WAVELENGTH` (microns) and `FLUX` (Jy)
- An `INT_TIMES` HDU with column `int_mid_MJD_UTC` for time-axis registration

Multiple files are sorted by observation time and concatenated into a single spectral time-series cube.

### HDF5

HDF5 files (`.h5`) are supported with datasets:

- `wavelength` — 1D array of wavelength values (microns)
- `flux` — 2D array of shape (n_times, n_wavelengths)
- `time` — 1D array of timestamps

## Model Grids

STAMP ships download scripts for 12 model atmosphere grids. After downloading, grids are stored under `model_grids/` with a standardized `index.csv` + `spectra/` layout.

| Grid | Teff Range (K) | log g | Metallicity | Source | Reference |
|------|----------------|-------|-------------|--------|-----------|
| ATMO 2020 CEQ | 200 -- 3000 | 2.5 -- 5.5 | Solar | [SVO](http://svo2.cab.inta-csic.es/theory/) | Phillips et al. (2020) |
| ATMO 2020 NEQ Strong | 200 -- 1800 | 2.5 -- 5.5 | Solar | SVO | Phillips et al. (2020) |
| ATMO 2020 NEQ Weak | 200 -- 1800 | 2.5 -- 5.5 | Solar | SVO | Phillips et al. (2020) |
| BT-Settl CIFIST | 1200 -- 7000 | 2.5 -- 5.5 | 0.0 | [Zenodo](https://zenodo.org/records/8015969) | Allard et al. (2012) |
| DRIFT-PHOENIX | 1000 -- 3000 | 3.0 -- 6.0 | -0.6 to +0.3 | SVO | Helling et al. (2008) |
| Exo-REM | Varies | Varies | Varies (+ C/O) | [LESIA](https://lesia.obspm.fr/exorem/) | Charnay et al. (2018) |
| Morley 2012 | 400 -- 1300 | 4.0 -- 5.5 | Solar (+ f_sed) | Morley et al. (2012) | Morley et al. (2012) |
| Phoenix-ACES | 2500 -- 5000 | 3.5 -- 5.5 | -1.0 to +0.5 | [Goettingen](https://phoenix.astro.physik.uni-goettingen.de/) | Husser et al. (2013) |
| Sonora Bobcat | 200 -- 2400 | 3.25 -- 5.5 | -0.5 to +0.5 | [Zenodo](https://zenodo.org/records/5063476) | Marley et al. (2021) |
| Sonora Diamondback | 900 -- 2400 | 3.5 -- 5.5 | -0.5 to +0.5 (+ f_sed) | [Zenodo](https://zenodo.org/records/12735103) | Morley et al. (2024) |
| Sonora Elf Owl (Y) | Varies | Varies | Varies | [Zenodo](https://zenodo.org/records/15150865) | Mukherjee et al. (2024) |
| Sonora Elf Owl (T, L) | Varies | Varies | Varies | [Zenodo](https://zenodo.org/records/15150874) | Mukherjee et al. (2024) |

To download all grids:

```bash
python scripts/download_all_grids.py
```

Individual grids can be downloaded separately (e.g., `python scripts/download_phoenix_grid.py`).

## Project Structure

```
SA3D/
├── app.py                  # Flask application factory
├── config.py               # Configuration (BASE_DIR, COLOR_SCALES, GRIDS_DIR)
├── wsgi.py                 # WSGI entry point for production servers
├── state.py                # Shared mutable state (progress tracking, results cache)
├── data_io.py              # FITS and HDF5 file readers
├── processing.py           # Binning, smoothing, regridding, variability analysis
├── plotting.py             # Plotly figure builders (3D surface + 2D heatmap)
├── fitting.py              # Chi-squared grid fitting + sinusoidal fitting
├── model_grids.py          # Grid loader with caching and unit conversion
├── cache_manager.py        # Disk-based dataset cache
├── routes/
│   ├── main.py             # Index page, static plot serving
│   ├── upload.py           # File upload and MAST query endpoints
│   ├── jobs.py             # Background job processing and progress tracking
│   └── fitting.py          # Model fitting API endpoints
├── templates/
│   └── index.html          # Single-page application template
├── static/
│   ├── css/                # Stylesheets (Tailwind, tour overlay)
│   ├── js/                 # Frontend modules (state, plots, fitting, export, tour)
│   └── demo_data/          # Bundled demo dataset
├── model_grids/            # Downloaded spectral grids (gitignored spectra)
├── scripts/                # Grid download utilities and fitting validation
└── requirements.txt
```

## Deployment

STAMP is deployed on Reclaim Cloud with gunicorn as the WSGI server. Key environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `GRIDS_DIR` | `model_grids/` | Path to model grid directory |
| `DEMO_DATA_DIR` | `static/demo_data/` | Path to bundled demo dataset |

An optional `config.yaml` in the project root can set `data_dir` for uploaded file storage.

## References

- Allard, F., Homeier, D., & Freytag, B. (2012). Models of very-low-mass stars, brown dwarfs and exoplanets. *Phil. Trans. R. Soc. A*, 370, 2765.
- Charnay, B., et al. (2018). A self-consistent cloud model for brown dwarfs and young giant exoplanets. *ApJ*, 854, 172.
- Helling, Ch., et al. (2008). A comprehensive nomenclature for brown dwarf and extrasolar giant planet atmosphere models. *A&A*, 485, 547.
- Husser, T.-O., et al. (2013). A new extensive library of PHOENIX stellar atmospheres and synthetic spectra. *A&A*, 553, A6.
- Marley, M. S., et al. (2021). The Sonora Brown Dwarf Atmosphere and Evolution Models. *ApJ*, 920, 85.
- Morley, C. V., et al. (2012). Neglected clouds in T and Y dwarf atmospheres. *ApJ*, 756, 172.
- Morley, C. V., et al. (2024). The Sonora Substellar Atmosphere Models. IV. Diamondback. *arXiv:2402.00758*.
- Mukherjee, S., et al. (2024). The Sonora Substellar Atmosphere Models. III. Elf Owl. *ApJ*, 963, 73.
- Phillips, M. W., et al. (2020). A new set of atmosphere and evolution models for cool T-Y brown dwarfs and giant exoplanets. *A&A*, 637, A38.
