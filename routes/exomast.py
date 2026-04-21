"""
Target parameter lookup — queries ExoMAST, SIMBAD, and Exoplanet.eu
to find published orbital and physical parameters for any target.
"""

import re
import requests
from flask import Blueprint, jsonify, request

exomast_bp = Blueprint('exomast', __name__, url_prefix='/exomast')

EXOMAST_BASE = 'https://exo.mast.stsci.edu/api/v0.1/exoplanets'
SIMBAD_TAP = 'https://simbad.cds.unistra.fr/simbad/sim-tap/sync'
EXOPLANET_EU_TAP = 'https://voparis-tap-planeto.obspm.fr/tap/sync'

# ── Helpers ──

_EXOMAST_KEYS = {
    'orbital_period':   'orbital_period',
    'Rp/Rs':            'rp_rs',
    'a/Rs':             'a_rs',
    'inclination':      'inclination',
    'eccentricity':     'eccentricity',
    'omega':            'omega',
    'Teff':             'teff',
    'stellar_gravity':  'stellar_logg',
    'Fe/H':             'metallicity',
    'Rs':               'star_radius_rsun',
    'Rp':               'planet_radius_rjup',
}


def _first(records, key):
    """Return the first non-null value for *key* across a list of records."""
    for rec in records:
        val = rec.get(key)
        if val is not None:
            return val
    return None


def _sanitize_adql(s):
    """Escape single quotes for ADQL string literals."""
    return s.replace("'", "''")


def _tap_query(endpoint, adql, timeout=10):
    """Execute a TAP synchronous ADQL query and return (col_names, rows).
    Returns ([], []) on any failure.
    """
    try:
        resp = requests.get(endpoint, params={
            'request': 'doQuery',
            'lang': 'adql',
            'format': 'json',
            'query': adql,
        }, timeout=timeout)
        if not resp.ok:
            return [], []
        data = resp.json()
    except (requests.RequestException, ValueError):
        return [], []

    meta = data.get('metadata', [])
    rows = data.get('data', [])
    col_names = [m.get('name', '') for m in meta]
    return col_names, rows


# ── ExoMAST ──

def _lookup_exomast(name):
    """Query ExoMAST.  Returns (params_dict, resolved_name) or (None, None)."""
    url = f'{EXOMAST_BASE}/{name}/properties/'
    try:
        resp = requests.get(url, timeout=10)
    except requests.RequestException:
        return None, None

    if not resp.ok:
        return None, None

    try:
        records = resp.json()
    except ValueError:
        return None, None

    if not records:
        return None, None

    params = {}
    for exo_key, our_key in _EXOMAST_KEYS.items():
        params[our_key] = _first(records, exo_key)

    resolved = _first(records, 'planet_name') or name
    return params, resolved


# ── SIMBAD ──

def _lookup_simbad(name):
    """Query SIMBAD TAP for spectral type, parallax/distance, RV, rotation.
    Tries exact identifier match, then dashes-to-spaces variant.
    Returns (params_dict, resolved_name) or (None, None).
    """
    variants = [name]
    normalised = name.replace('-', ' ').replace('_', ' ')
    if normalised != name:
        variants.append(normalised)

    for variant in variants:
        safe = _sanitize_adql(variant)
        adql = (
            "SELECT TOP 1 b.main_id, b.sp_type, b.plx_value, "
            "b.rvz_radvel, r.vsini, v.period "
            "FROM basic AS b "
            "JOIN ident AS i ON i.oidref = b.oid "
            "LEFT JOIN mesRot AS r ON r.oidref = b.oid "
            "LEFT JOIN mesVar AS v ON v.oidref = b.oid "
            f"WHERE i.id = '{safe}'"
        )
        cols, rows = _tap_query(SIMBAD_TAP, adql, timeout=10)
        if not rows:
            continue

        rec = dict(zip(cols, rows[0]))
        params = {}
        resolved = rec.get('main_id', name)

        sp = rec.get('sp_type')
        if sp:
            params['spectral_type'] = sp.strip()

        plx = rec.get('plx_value')
        if plx and plx > 0:
            params['distance_pc'] = round(1000.0 / plx, 3)

        rv = rec.get('rvz_radvel')
        if rv is not None:
            params['radial_velocity'] = rv

        vsini = rec.get('vsini')
        if vsini is not None:
            params['v_sini'] = vsini

        period = rec.get('period')
        if period is not None:
            params['rotation_period'] = period

        return params, resolved

    return None, None


# ── Exoplanet.eu ──

def _make_exoeu_pattern(name):
    """Build a SQL LIKE pattern for exoplanet.eu from a target name.
    e.g. 'SIMP-J013656.5+093347.3' → 'SIMP%0136%'
         'WASP-39 b'               → '%WASP 39 b%'
    """
    cleaned = name.replace('-', ' ').replace('_', ' ').strip()

    # Coordinate-style names: extract prefix + first significant digits
    m = re.match(r'([A-Za-z]+(?:\s+[A-Za-z])?)\s*(\d{3,4})', cleaned)
    if m:
        prefix = m.group(1).strip()
        digits = m.group(2)[:4]
        return f'{prefix}%{digits}%'

    return f'%{cleaned}%'


def _lookup_exoplanet_eu(name):
    """Query Exoplanet.eu TAP for physical & orbital parameters.
    Returns (params_dict, resolved_name) or (None, None).
    """
    pattern = _sanitize_adql(_make_exoeu_pattern(name))
    adql = (
        "SELECT TOP 1 target_name, mass, radius, "
        "temp_measured, log_g, orbital_period, "
        "semi_major_axis, inclination, eccentricity, omega, "
        "star_distance, star_teff, star_metallicity "
        "FROM exoplanet "
        f"WHERE target_name LIKE '{pattern}'"
    )
    cols, rows = _tap_query(EXOPLANET_EU_TAP, adql, timeout=10)
    if not rows:
        return None, None

    rec = dict(zip(cols, rows[0]))
    params = {}
    resolved = rec.get('target_name', name)

    _map = {
        'mass':             'mass_mjup',
        'radius':           'radius_rjup',
        'temp_measured':    'teff',
        'log_g':            'stellar_logg',
        'orbital_period':   'orbital_period',
        'semi_major_axis':  'semi_major_axis',
        'inclination':      'inclination',
        'eccentricity':     'eccentricity',
        'omega':            'omega',
        'star_distance':    'distance_pc',
        'star_metallicity': 'metallicity',
    }
    for src_key, dest_key in _map.items():
        val = rec.get(src_key)
        if val is not None:
            params[dest_key] = val

    # Use star Teff as fallback if no measured temp
    if 'teff' not in params and rec.get('star_teff') is not None:
        params['teff'] = rec['star_teff']

    return params, resolved


# ── Merge ──

_SOURCE_LABELS = ['ExoMAST', 'Exoplanet.eu', 'SIMBAD']


def _merge_results(*results):
    """Merge (params, name) tuples.  Earlier entries take priority.
    Returns (merged_params, sources_list, resolved_name).
    """
    merged = {}
    sources = []
    resolved = None

    for i, (params, rname) in enumerate(results):
        if not params:
            continue
        contributed = False
        for k, v in params.items():
            if v is not None and k not in merged:
                merged[k] = v
                contributed = True
        if contributed and i < len(_SOURCE_LABELS):
            sources.append(_SOURCE_LABELS[i])
        if rname and not resolved:
            resolved = rname

    return merged, sources, resolved


# ── Routes ──

@exomast_bp.route('/lookup/<path:planet_name>')
def lookup(planet_name):
    """Unified target parameter lookup — ExoMAST → Exoplanet.eu → SIMBAD."""

    # 1. ExoMAST (+ " b" retry for planet names missing the letter)
    exomast_params, exomast_name = _lookup_exomast(planet_name)
    if not exomast_params and not re.search(r'\s[a-z]$', planet_name, re.I):
        exomast_params, exomast_name = _lookup_exomast(planet_name + ' b')

    # 2. SIMBAD + Exoplanet.eu — always query both for complementary params
    simbad_params, simbad_name = _lookup_simbad(planet_name)
    exoeu_params, exoeu_name = _lookup_exoplanet_eu(planet_name)

    # Merge: ExoMAST > Exoplanet.eu > SIMBAD
    merged, sources, resolved = _merge_results(
        (exomast_params, exomast_name),
        (exoeu_params, exoeu_name),
        (simbad_params, simbad_name),
    )

    if not merged:
        return jsonify(found=False,
                       error='Target not found in any catalog '
                             '(ExoMAST, SIMBAD, Exoplanet.eu)')

    # Compute derived parameters if missing
    rs = merged.get('star_radius_rsun')
    if rs and rs > 0:
        if 'a_rs' not in merged and 'semi_major_axis' in merged:
            merged['a_rs'] = round(merged['semi_major_axis'] * 215.032 / rs, 4)
        if 'rp_rs' not in merged and 'planet_radius_rjup' in merged:
            merged['rp_rs'] = round(merged['planet_radius_rjup'] * 0.10273 / rs, 6)

    return jsonify(found=True,
                   planet_name=resolved or planet_name,
                   params=merged,
                   sources=sources,
                   found_keys=list(merged.keys()))


@exomast_bp.route('/autocomplete')
def autocomplete():
    """Proxy ExoMAST autocomplete suggestions."""
    term = request.args.get('term', '').strip()
    if len(term) < 2:
        return jsonify([])

    url = f'{EXOMAST_BASE}/autocomplete/'
    try:
        resp = requests.get(url, params={'term': term}, timeout=5)
        return jsonify(resp.json() if resp.ok else [])
    except Exception:
        return jsonify([])
