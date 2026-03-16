"""
config.py — App-level constants for the MOPADI annotation platform.
"""

import os

# Load .env if present
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# Max new (non-password-protected) accounts that can be created per calendar day
MAX_NEW_ACCOUNTS_PER_DAY = 10

# Flask secret key — change before deploying publicly
SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "mopadi-study-2026-change-me")

# Admin download key — set ADMIN_KEY env var on the server, never commit a real value
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")

# Password-protected expert accounts (others may log in freely)
# IDs and passwords are loaded from .env so nothing is hardcoded here
EXPERT_PASSWORDS = {}
for _i in range(1, 20):
    _id  = os.environ.get(f"EXPERT_ID_{_i}", "")
    _pwd = os.environ.get(f"EXPERT_PASSWORD_{_id.upper().replace('-','_')}", "")
    if _id and _pwd:
        EXPERT_PASSWORDS[_id] = _pwd

# Path to the pre-generated study configuration (committed to git)
STUDY_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "study_config.json")

# Directory where per-expert result JSON files are saved
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

# Hamming distance below which a pHash match is considered reliable
# (only relevant during extract_figures.py, not at runtime)
PHASH_THRESHOLD = 15

# Task 2 morphological features, keyed by section index.
# Sections not listed here fall back to MORPHOLOGICAL_FEATURES_DEFAULT.
MORPHOLOGICAL_FEATURES_DEFAULT = [
    ("nuclear_pleomorphism",        "Nuclear pleomorphism"),
    ("abnormal_mitotic_figures",    "Abnormal mitotic figures"),
    ("glandular_disorganization",   "Glandular disorganization"),
    ("necrosis",                    "Necrosis / tissue artifacts"),
    ("inflammatory_infiltrate",     "Inflammatory infiltrate"),
    ("stromal_changes",             "Stromal changes"),
    ("chromatin_abnormalities",     "Chromatin abnormalities"),
    ("other",                       "Other (specify below)"),
]

_CRC_FEATURES = [
    ("gland_formation",       "Gland formation"),
    ("goblet_cells_mucin",    "Goblet-like cells / intracellular mucin"),
    ("extracellular_mucin",   "Extracellular mucin"),
    ("nuclear_atypia",        "Nuclear atypia / hyperchromasia"),
    ("invasive_growth",       "Invasive / disorganized growth pattern"),
    ("desmoplastic_stroma",   "Desmoplastic stroma"),
    ("necrotic_debris",       "Necrotic debris"),
    ("artifact",              "Artifact (synthetic or imaging)"),
    ("other",                 "Other (specify below)"),
]

_MSI_FEATURES = [
    ("lymphocytes",          "Presence of lymphocytes"),
    ("solid_growth",         "Solid growth pattern / sheet-like"),
    ("glandular_pattern",    "Glandular pattern"),
    ("extracellular_mucin",  "Extracellular mucin pools"),
    ("intracyto_mucin",      "Intracytoplasmic mucin"),
    ("signet_ring",          "Signet ring cells"),
    ("dirty_necrosis",       "Presence of dirty necrosis"),
    ("neutrophil_like",      "Neutrophil-like cells"),
    ("artifact",             "Artifact (synthetic or imaging)"),
    ("other",                "Other (specify below)"),
]

_LUNG_FEATURES = [
    ("glandular_acinar",        "Glandular / acinar structures"),
    ("lepidic_pattern",         "Lepidic growth pattern"),
    ("papillary_structures",    "Papillary / micropapillary structures"),
    ("mucin_vacuoles",          "Mucin production / intracellular vacuoles"),
    ("squamous_keratinization", "Squamous differentiation / keratinization"),
    ("keratin_pearls",          "Keratin pearls"),
    ("intercellular_bridges",   "Intercellular bridges"),
    ("artifact",                "Artifact (synthetic or imaging)"),
    ("other",                   "Other (specify below)"),
]

SECTION_FEATURES = {
    0: _CRC_FEATURES,   # CRC TUM→NORM
    1: _CRC_FEATURES,   # CRC NORM→TUM
    2: _MSI_FEATURES,   # CRC MSIH→nonMSIH
    3: _MSI_FEATURES,   # CRC nonMSIH→MSIH
    6: _LUNG_FEATURES,  # Lung LUSC→LUAD
    7: _LUNG_FEATURES,  # Lung LUAD→LUSC
}
