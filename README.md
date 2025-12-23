# STAMP - Spectral Time-series Analysis and Mapping Program

**Authors:** Anthony Muñoz-Perez (munozanthony196@gmail.com) & Dr. Niall Whiteford (niallwhiteford@gmail.com)  
**Institution:** The American Museum of Natural History

## Overview

STAMP is a web-based visualization tool designed to analyze and visualize spectroscopic time-series data from JWST (James Webb Space Telescope) observations downloaded from MAST (Mikulski Archive for Space Telescopes). It provides interactive 3D surface plots, heatmaps, and animated spectrum videos to help astronomers study how astronomical objects' spectra change over time.

## What Does STAMP Do?

STAMP transforms complex multi-dimensional spectroscopic data into intuitive visualizations that reveal temporal variations in astronomical spectra. The tool is specifically designed for:

1. **Time-Series Spectroscopy Analysis**: Visualize how spectra evolve over observation periods
2. **Variability Studies**: Identify and analyze spectral variability patterns
3. **Multi-Visit Data**: Handle data from multiple observation visits with gap detection
4. **Wavelength-Specific Analysis**: Focus on specific wavelength bands or custom spectral regions

### Key Features

#### Data Processing
- **Multi-Format Support**: Reads FITS files and HDF5 (.h5) files from MAST archives
- **Automatic Integration**: Combines multiple observation files into coherent time-series
- **Visit Detection**: Automatically identifies separate observation visits based on temporal gaps
- **Data Normalization**: Normalizes flux to reveal variability patterns
- **Gap Interpolation**: Optional linear interpolation to fill gaps between visits

#### Visualization Modes

1. **3D Surface Plots**
   - Interactive 3D visualization showing wavelength, time, and flux/variability
   - Separate surfaces for each observing visit
   - Customizable color scales (Viridis, Plasma, Inferno, Magma, and more)
   - Toggle between raw flux and variability percentage display

2. **2D Heatmaps**
   - Compact representation of spectral time-series data
   - Same data as surface plot in a 2D format
   - Easier pattern recognition for large datasets

3. **Animated Spectrum Videos**
   - Frame-by-frame progression through time
   - Shows how individual spectra evolve
   - Exportable as MP4 video files

#### Interactive Controls

- **Wavelength Range Filtering**: Focus on specific spectral regions
- **Time Range Filtering**: Analyze specific observation periods
- **Variability Range Control**: Adjust color scale limits for better contrast
- **Custom Wavelength Bands**: Define and highlight specific spectral features
- **Integration Limiting**: Process subset of integrations for faster preview
- **Colorscale Selection**: Choose from 10 different scientific color scales

## How STAMP Works

### Architecture

STAMP is built as a Flask web application with the following components:

```
STAMP/
├── app.py              # Main Flask application (1275 lines)
├── wsgi.py            # WSGI entry point for deployment
├── Procfile           # Heroku deployment configuration
├── requirements.txt   # Python dependencies
├── runtime.txt        # Python version specification
├── templates/
│   └── index.html     # Web interface
└── static/
    ├── css/           # Stylesheets
    └── js/            # JavaScript for interactivity
```

### Data Processing Pipeline

1. **Upload & Extraction**
   - User uploads ZIP file containing MAST data
   - Server extracts and identifies FITS/HDF5 files
   - Files are sorted by observation timestamp

2. **Integration Loading**
   - Each file contains multiple spectroscopic integrations
   - Extracts: wavelength arrays, flux values, uncertainties, timestamps
   - Handles different MAST data formats and header variations

3. **Time-Series Construction**
   - Aligns wavelength grids across integrations
   - Interpolates to common wavelength grid if needed
   - Constructs 2D flux array: [wavelength × time]
   - Converts timestamps to hours from first observation

4. **Normalization**
   - Calculates median spectrum across all integrations
   - Normalizes each spectrum by dividing by median
   - Results show relative variability (deviations from 1.0)

5. **Visit Segmentation**
   - Analyzes time gaps between integrations
   - Identifies separate observation visits (default gap threshold: 0.5 hours)
   - Creates separate 3D surfaces for each visit

6. **Processing & Smoothing**
   - Optional binning to reduce data volume for display
   - Gaussian smoothing (configurable sigma) for noise reduction
   - Applies user-specified wavelength and time range filters

7. **Visualization Generation**
   - Creates Plotly interactive plots
   - Generates separate JSON objects for 3D and 2D views
   - Produces video frames if spectrum animation requested

### Technical Implementation

#### Key Technologies

- **Backend**: Flask 3.0.3 (Python web framework)
- **Scientific Computing**: 
  - NumPy 2.2.1 (array operations)
  - SciPy 1.14.1 (statistics, interpolation)
  - Astropy 7.1.0 (FITS file handling, time conversions)
  - h5py 3.14.0 (HDF5 file handling)
  
- **Visualization**: 
  - Plotly 5.24.1 (interactive plots)
  - FFmpeg (video generation via subprocess)
  
- **Frontend**: 
  - Tailwind CSS (responsive UI)
  - Vanilla JavaScript (client-side interactivity)

#### Asynchronous Processing

For large datasets, STAMP uses a background job system:

```python
# Job tracking with threading
PROGRESS = {}  # Job status tracking
RESULTS = {}   # Completed results storage
```

- Jobs run in background threads
- Progress updates via `/progress/<job_id>` endpoint
- Client polls for status updates
- Results retrieved via `/results/<job_id>` when complete

#### Data Structures

**Integration Object:**
```python
{
    'wavelength': np.array,  # 1D wavelength array
    'flux': np.array,        # 1D flux array
    'error': np.array,       # 1D uncertainty array
    'time': float/Time       # MJD timestamp
}
```

**Processed Data:**
```python
wavelength_1d: np.array  # Shape: [n_wavelengths]
flux_2d: np.array        # Shape: [n_wavelengths, n_integrations]
time_1d: np.array        # Shape: [n_integrations]
errors_2d: np.array      # Shape: [n_wavelengths, n_integrations]
```

### API Endpoints

- `GET /` - Main web interface
- `POST /upload_mast` - Synchronous data upload and processing (deprecated)
- `POST /start_mast` - Asynchronous job submission
- `GET /progress/<job_id>` - Poll job progress
- `GET /results/<job_id>` - Retrieve completed results
- `POST /upload_spectrum_frames` - Generate video from frames
- `GET /download_plots` - Download visualization package
- `GET /plots/<filename>` - Serve generated plot files

## Installation

### Requirements

- Python 3.11+ (specified in runtime.txt)
- FFmpeg (for video generation)
- ~150 MB of Python packages (see requirements.txt)

### Local Setup

```bash
# Clone the repository
git clone https://github.com/BDNYC/STAMP.git
cd STAMP

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py
```

The application will start on `http://localhost:5000`

### Production Deployment

STAMP is configured for deployment on Heroku or similar WSGI platforms:

```bash
# Using Gunicorn (as specified in Procfile)
gunicorn app:app
```

The `wsgi.py` file provides the WSGI entry point.

## Usage

### Basic Workflow

1. **Prepare Data**
   - Download JWST time-series spectroscopy from MAST
   - Ensure data is in FITS or HDF5 format
   - Package files in a ZIP archive

2. **Upload to STAMP**
   - Open STAMP web interface
   - Click "Choose File" and select your ZIP file
   - Configure visualization parameters:
     - Number of integrations to plot (0 = all)
     - Enable/disable linear interpolation
     - Select color scale
     - Set Z-axis display mode (flux vs. variability)

3. **Set Data Ranges** (Optional)
   - Wavelength range (in µm)
   - Time range (in hours from start)
   - Variability/flux range (for color scale)

4. **Define Custom Bands** (Optional)
   - Add wavelength regions of interest
   - Name each band (e.g., "H2O", "CH4", "CO2")
   - Bands appear as interactive filters in plots

5. **Generate Visualizations**
   - Click "Upload and Visualize"
   - Wait for processing (progress bar shows status)
   - Explore interactive plots when ready

6. **Interact with Results**
   - Rotate/zoom 3D surface plot
   - Toggle between full spectrum and custom bands
   - Hover over data points for exact values
   - Download plots package (ZIP with HTML + video)

### Advanced Features

#### Custom Wavelength Bands

Define spectral regions to highlight specific features:

```json
[
  {"name": "Water Band", "start": 2.5, "end": 3.0},
  {"name": "Methane", "start": 3.2, "end": 3.5}
]
```

Clicking band buttons in the visualization will:
- Highlight the band region in full color
- Dim out-of-band regions (gray, 35% opacity)

#### Z-Axis Display Modes

- **Variability (%)**: Shows (flux/median - 1) × 100
  - Best for identifying temporal changes
  - Symmetric around 0%
  - Default mode for exoplanet transit/eclipse observations

- **Raw Flux**: Shows actual flux values
  - Useful for absolute measurements
  - Units displayed from FITS header (typically MJy)

#### Interpolation Option

When enabled:
- Fills temporal gaps between visits
- Uses linear interpolation
- Creates continuous 3D surface
- Useful for visualization but may hide real data gaps

When disabled (default):
- Creates separate surfaces for each visit
- Preserves data authenticity
- Shows temporal gaps explicitly

## Data Format Support

### FITS Files (JWST Pipeline Output)

Expected structure:
- `EXTRACT1D` extension with spectroscopic data
- `INT_TIMES` extension with integration timestamps
- Multiple `EXTRACT1D,N` extensions (one per integration)

Required columns:
- `WAVELENGTH`: Wavelength array
- `FLUX`: Flux measurements
- `FLUX_ERROR`: Uncertainty estimates (optional)

### HDF5 Files (Eureka! Pipeline)

Supported key variations:
- Flux: `calibrated_optspec`, `stdspec`, `optspec`
- Wavelength: `eureka_wave_1d`, `wave_1d`, `wavelength`, `wave`
- Time: `time`, `bmjd`, `mjd`, `bjd`, `time_bjd`, `time_mjd`
- Error: `calibrated_opterr`, `stdvar`, `error`, `flux_error`, `sigma`

Note: If error key ends with `stdvar`, STAMP takes the square root to convert variance to standard deviation.

## Output

STAMP generates a downloadable ZIP package containing:

1. **surface_plot_YYYYMMDD_HHMMSS.html**
   - Standalone 3D surface visualization
   - Interactive with Plotly controls
   - Band filtering buttons

2. **heatmap_plot_YYYYMMDD_HHMMSS.html**
   - Standalone 2D heatmap
   - Same band filtering capabilities

3. **combined_plots_YYYYMMDD_HHMMSS.html**
   - All visualizations in one page
   - Synchronized band controls

4. **spectrum_YYYYMMDD_HHMMSS.mp4** (if video generated)
   - Animated progression through time
   - H.264 encoded, optimized for web
   - Configurable frame rate and quality

All HTML files are self-contained and can be opened in any modern browser without internet connection (Plotly library is embedded).

## Performance Considerations

- **Large Datasets**: For >1000 integrations, consider limiting display count
- **Memory Usage**: Full dataset loaded into RAM during processing
- **Processing Time**: Scales with (wavelengths × integrations)
  - ~100 integrations: seconds
  - ~1000 integrations: tens of seconds
  - ~10000 integrations: minutes

The asynchronous job system (`/start_mast`) is recommended for large datasets to prevent browser timeouts.

## Scientific Applications

STAMP is particularly useful for:

1. **Exoplanet Atmosphere Studies**
   - Transit spectroscopy time-series
   - Eclipse observations
   - Phase curve analysis

2. **Variable Star Monitoring**
   - Spectral evolution tracking
   - Pulsation studies
   - Emission line variability

3. **AGN Observations**
   - Broad line region dynamics
   - Continuum variability
   - Reverberation mapping

4. **Quality Control**
   - Identifying instrumental artifacts
   - Checking data consistency across visits
   - Validating reduction pipelines

## Troubleshooting

### Common Issues

**"No MAST zip file provided"**
- Ensure file is selected before clicking upload
- Check file is actually a ZIP archive

**"Error reading FITS file"**
- Verify FITS files follow JWST pipeline format
- Check for required extensions (INT_TIMES, EXTRACT1D)

**FFmpeg not found**
- Install FFmpeg: `apt install ffmpeg` (Linux) or `brew install ffmpeg` (Mac)
- Ensure FFmpeg is in system PATH

**Processing appears stuck**
- Check browser console for errors
- For large datasets, use `/start_mast` endpoint (asynchronous)
- Limit number of integrations for initial testing

**Plots appear empty**
- Check wavelength/time/variability ranges aren't too restrictive
- Verify data contains finite values (not all NaN)
- Try disabling smoothing or interpolation

## Future Development

Potential enhancements:
- Support for additional data formats (CSV, ASCII tables)
- Real-time streaming for live observations
- Advanced statistical analysis tools
- Machine learning-based anomaly detection
- Multi-target comparison mode
- Export to publication-ready formats

## Contributing

This tool is actively developed at the American Museum of Natural History. For questions, bug reports, or feature requests, contact the authors.

## License

[License information to be added]

## Acknowledgments

STAMP was developed to support JWST spectroscopic observations and utilizes data from the Mikulski Archive for Space Telescopes (MAST).

