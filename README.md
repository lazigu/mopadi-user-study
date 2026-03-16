# MOPADI Expert Annotation Platform

A Flask web app for expert annotation of synthetic vs. real histopathology images.

## Setup

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/). If not yet installed run:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then clone the repository and create the environment:
```bash
git clone <repo>
cd mopadiui
uv sync
```

Copy the `.env` file into the project root (see below).

## Configuration

Create a `.env` file in the project root with the following variables:

```env
ADMIN_KEY=<secret key for downloading results>
FLASK_SECRET_KEY=<secret key>

# In case of special expert accounts
EXPERT_ID_1=<expert_id>
EXPERT_PASSWORD_<EXPERT_ID_1_UPPERCASE>=<password>

EXPERT_ID_2=<expert_id>
EXPERT_PASSWORD_<EXPERT_ID_2_UPPERCASE>=<password>
# ...
```

Expert IDs without a matching password entry can log in freely (no password required).

## Running

```bash
uv run flask run --host=0.0.0.0 --port=3000
```

The app is then accessible at `http://<server-ip>:3000`.


## Project Structure

```
mopadiui/
├── app.py               # Main Flask application
├── config.py            # Configuration (loads .env)
├── study_config.json    # Study design: sections, images, task1/task2 ordering
├── pyproject.toml       # Python dependencies (managed by uv)
├── results/             # Per-expert result JSON files (one per participant)
├── static/              # CSS, JS
└── templates/           # Jinja2 HTML templates
```

## Study Design

The study has 10 sections across 4 tissue types (colorectal, liver, lung, breast). Each section has two tasks:

- **Task 1** — Rate each image as Real or Synthetic (30 images per section)
- **Task 2** — Identify morphological features in pairs of images (15 pairs per section)

Image order is fixed by a per-expert seed stored in the result file.

## Expert Account States

Section states are stored per-expert in `results/expert_<id>.json`:

| Flag | Effect |
|------|--------|
| `locked: true` | Section fully locked — Task 1 and Task 2 both read-only |
| `task1_locked: true` | Task 1 read-only, Task 2 still accessible |
| `task2_locked: true` | Task 2 read-only, Task 1 still accessible |
| `task1_override_ids: [...]` | Specific Task 1 images can be re-submitted even when locked — shown with ⚠ in sidebar |
