"""
app.py — MOPADI Expert Annotation Platform (Flask)

Routes:
  GET  /                                     Landing page
  POST /start                                Create or resume session
  GET  /section/<sec_idx>/intro              Section context card
  GET  /section/<sec_idx>/task1/<img_idx>    Rate image Real/Synthetic
  POST /section/<sec_idx>/task1/<img_idx>    Save Task 1 rating
  GET  /section/<sec_idx>/task1_complete     Task 1 done interstitial
  GET  /section/<sec_idx>/task2/<pair_idx>   Morphological features (pair of images)
  POST /section/<sec_idx>/task2/<pair_idx>   Save Task 2 features for both images
  GET  /section/<sec_idx>/complete           Section complete
  GET  /complete                             Study complete
  GET  /proxy_image/<img_id>                 Dev fallback: serve from local_path
"""

import io
import json
import os
import zipfile
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from config import (
    ADMIN_KEY,
    EXPERT_PASSWORDS,
    MAX_NEW_ACCOUNTS_PER_DAY,
    MORPHOLOGICAL_FEATURES_DEFAULT,
    SECTION_FEATURES,
    RESULTS_DIR,
    SECRET_KEY,
    STUDY_CONFIG_PATH,
)

app = Flask(__name__)
app.secret_key = SECRET_KEY

# ---------------------------------------------------------------------------
# Load study config at startup
# ---------------------------------------------------------------------------
if not os.path.exists(STUDY_CONFIG_PATH):
    raise FileNotFoundError(
        f"study_config.json not found at {STUDY_CONFIG_PATH}. "
        "Run extract_figures.py first."
    )

with open(STUDY_CONFIG_PATH) as f:
    STUDY = json.load(f)

SECTIONS = STUDY["sections"]
N_SECTIONS = len(SECTIONS)

os.makedirs(RESULTS_DIR, exist_ok=True)


def get_n_groups(sec):
    """Number of Task 2 groups (may be less than len(images)//group_size for sections
    that have extra standalone task1-only images appended at the end)."""
    return sec.get("n_groups") or len(sec["images"]) // sec.get("group_size", 2)

# Build a flat index: img_id -> {local_path, hf_url, ...}
IMG_INDEX = {}
for sec in SECTIONS:
    for img in sec["images"]:
        IMG_INDEX[img["img_id"]] = img


# ---------------------------------------------------------------------------
# Results helpers
# ---------------------------------------------------------------------------

def results_path(expert_id):
    safe_id = "".join(c for c in expert_id if c.isalnum() or c in "-_.")
    return os.path.join(RESULTS_DIR, f"expert_{safe_id}.json")


def load_results(expert_id):
    path = results_path(expert_id)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def save_results(expert_id, data):
    """Atomic write to prevent corrupt JSON on crash."""
    path = results_path(expert_id)
    tmp = path + ".tmp"
    data["last_updated"] = utcnow()
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def ensure_section(results, sec_idx):
    """Initialise section dict if not present."""
    sec_key = str(sec_idx)
    if "sections" not in results:
        results["sections"] = {}
    if sec_key not in results["sections"]:
        results["sections"][sec_key] = {
            "section_label": SECTIONS[sec_idx]["label"],
            "task1_started_at": None,
            "task1_completed_at": None,
            "task2_started_at": None,
            "task2_completed_at": None,
            "task2_locked": sec_idx in (4, 5, 8, 9),
            "annotations": {},
        }
    sec = results["sections"][sec_key]
    sec.setdefault("annotations", {})
    sec.setdefault("task1_started_at", None)
    sec.setdefault("task1_completed_at", None)
    sec.setdefault("task2_started_at", None)
    sec.setdefault("task2_completed_at", None)
    return sec


def ensure_annotation(sec_data, img_id):
    if img_id not in sec_data["annotations"]:
        sec_data["annotations"][img_id] = {"img_id": img_id, "task1": None, "task2": None}
    return sec_data["annotations"][img_id]


def overall_pct(expert_id):
    """Compute overall study completion percentage (task1 + task2 combined)."""
    results = load_results(expert_id)
    total_needed = total_done = 0
    for sec_idx, sec_cfg in enumerate(SECTIONS):
        images = sec_cfg["images"]
        task1_order = sec_cfg.get("task1_order", list(range(len(images))))
        n_groups = get_n_groups(sec_cfg)
        group_size = sec_cfg.get("group_size", 2)
        group_images = images[:n_groups * group_size]
        annotations = results.get("sections", {}).get(str(sec_idx), {}).get("annotations", {})
        total_needed += len(task1_order) + len(group_images)
        total_done += sum(
            1 for raw_idx in task1_order
            if annotations.get(images[raw_idx]["img_id"], {}).get("task1")
        )
        total_done += sum(
            1 for img in group_images
            if annotations.get(img["img_id"], {}).get("task2")
        )
    return int(total_done / total_needed * 100) if total_needed else 0


# ---------------------------------------------------------------------------
# Sidebar context processor — injected into every template
# ---------------------------------------------------------------------------

@app.context_processor
def inject_sidebar():
    expert_id = session.get("expert_id")
    if not expert_id:
        return {"incomplete": []}
    results = load_results(expert_id)
    sections_data = results.get("sections", {})

    _sec_groups = {0: "Colorectal", 1: "Colorectal", 2: "Colorectal", 3: "Colorectal",
                   4: "Liver", 5: "Liver", 6: "Lung", 7: "Lung",
                   8: "Breast", 9: "Breast"}
    _short_labels = {
        0: "TUM→NORM", 1: "NORM→TUM",
        2: "MSIH→nonMSIH", 3: "nonMSIH→MSIH",
        4: "LIHC→CHOL", 5: "CHOL→LIHC",
        6: "LUSC→LUAD", 7: "LUAD→LUSC",
        8: "ILC→IDC", 9: "IDC→ILC",
    }
    sidebar = []
    prev_group = None
    for sec_idx, sec in enumerate(SECTIONS):
        sec_key = str(sec_idx)
        sec_data = sections_data.get(sec_key, {})
        locked = sec_data.get("locked", False)
        task1_locked = sec_data.get("task1_locked", False)
        task2_locked = sec_data.get("task2_locked", sec_idx in (4, 5, 8, 9))
        annotations = sec_data.get("annotations", {})

        task1_order = sec.get("task1_order", list(range(len(sec["images"]))))
        n_task1 = len(task1_order)
        task1_done = sum(
            1 for i in task1_order
            if annotations.get(sec["images"][i]["img_id"], {}).get("task1") is not None
        )

        n_pairs = get_n_groups(sec)
        group_size = sec.get("group_size", 2)
        task2_done = sum(
            1 for pair_idx in range(n_pairs)
            if all(
                annotations.get(sec["images"][pair_idx * group_size + offset]["img_id"], {}).get("task2") is not None
                for offset in [0, group_size - 1]
            )
        )

        # Pending overrides: locked section with unanswered override images
        override_ids = sec_data.get("task1_override_ids", [])
        pending_overrides = (locked or task1_locked) and any(
            annotations.get(oid, {}).get("task1") is None for oid in override_ids
        )

        group = _sec_groups.get(sec_idx, "")
        sidebar.append({
            "sec_idx": sec_idx,
            "short_label": _short_labels.get(sec_idx) or sec.get("short_label", sec["label"]),
            "group": group,
            "show_group_header": group != prev_group,
            "locked": locked,
            "task1_locked": task1_locked,
            "task2_locked": task2_locked,
            "pending_overrides": pending_overrides,
            "task1_done": task1_done,
            "task1_total": n_task1,
            "task1_complete": task1_done >= n_task1,
            "task2_done": task2_done,
            "task2_total": n_pairs,
            "task2_complete": task2_done >= n_pairs,
            "section_complete": task1_done >= n_task1 and task2_done >= n_pairs,
        })
        prev_group = group
    return {"sidebar_sections": sidebar, "incomplete": []}


# ---------------------------------------------------------------------------
# Resume / position logic
# ---------------------------------------------------------------------------

def compute_redirect(expert_id):
    """
    Scan the results file and return a redirect to where the expert should be.
    Called on POST /start and as a fallback guard.
    """
    results = load_results(expert_id)
    sections_data = results.get("sections", {})

    for sec_idx, sec_cfg in enumerate(SECTIONS):
        sec_key = str(sec_idx)

        # Locked sections count as fully complete — skip them
        if sections_data.get(sec_key, {}).get("locked"):
            continue

        images = sec_cfg["images"]
        annotations = sections_data.get(sec_key, {}).get("annotations", {})

        # Check Task 1 completeness (only images in task1_order are required)
        task1_order = sec_cfg.get("task1_order", list(range(len(images))))
        task1_done = all(
            annotations.get(images[raw_idx]["img_id"], {}).get("task1") is not None
            for raw_idx in task1_order
        )
        if not task1_done:
            for img_idx, raw_idx in enumerate(task1_order):
                img = images[raw_idx]
                if annotations.get(img["img_id"], {}).get("task1") is None:
                    return redirect(url_for("task1", sec_idx=sec_idx, img_idx=img_idx))

        # Task 1 done; check Task 2 (iterated as groups)
        sec_state = sections_data.get(sec_key, {})
        if sec_state.get("task2_locked"):
            continue

        n_groups = get_n_groups(sec_cfg)
        group_size = sec_cfg.get("group_size", 2)
        group_images = images[:n_groups * group_size]  # excludes any standalone task1-only images
        task2_started = any(
            annotations.get(img["img_id"], {}).get("task2") is not None
            for img in group_images
        )
        task2_done = task2_started and all(
            annotations.get(img["img_id"], {}).get("task2") is not None
            for img in group_images
        )
        if not task2_started:
            # Show the task1_complete interstitial before starting task2
            return redirect(url_for("task1_complete", sec_idx=sec_idx))
        if not task2_done:
            for pair_idx in range(n_groups):
                group = images[pair_idx * group_size:(pair_idx + 1) * group_size]
                if any(annotations.get(g["img_id"], {}).get("task2") is None for g in group):
                    return redirect(url_for("task2", sec_idx=sec_idx, pair_idx=pair_idx))

    return redirect(url_for("study_complete"))


# ---------------------------------------------------------------------------
# Auth guard decorator
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("expert_id"):
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", protected_ids=list(EXPERT_PASSWORDS.keys()))


@app.route("/start", methods=["POST"])
def start():
    expert_id = request.form.get("expert_id", "").strip()
    _protected_ids = list(EXPERT_PASSWORDS.keys())
    if not expert_id:
        return render_template("index.html", error="Please enter your expert ID.", protected_ids=_protected_ids)

    if expert_id in EXPERT_PASSWORDS:
        password = request.form.get("password", "").strip()
        if password != EXPERT_PASSWORDS[expert_id]:
            session.pop("expert_id", None)
            return render_template("index.html", error="Incorrect password.", protected_ids=_protected_ids, prefill_id=expert_id)

    session["expert_id"] = expert_id

    results = load_results(expert_id)
    if not results or not results.get("started_at"):
        # New session — check daily account creation limit (exempt: password-protected accounts)
        if expert_id not in EXPERT_PASSWORDS:
            today = datetime.now(timezone.utc).date().isoformat()
            new_today = 0
            for fn in os.listdir(RESULTS_DIR):
                if not fn.endswith(".json") or fn.endswith(".tmp"):
                    continue
                try:
                    with open(os.path.join(RESULTS_DIR, fn)) as _f:
                        d = json.load(_f)
                    if d.get("started_at", "")[:10] == today:
                        new_today += 1
                except Exception:
                    pass
            if new_today >= MAX_NEW_ACCOUNTS_PER_DAY:
                return render_template("index.html",
                    error="Registration is temporarily limited. Please try again tomorrow or contact the study coordinator.",
                    protected_ids=list(EXPERT_PASSWORDS.keys()))
        if not results:
            results = {"expert_id": expert_id}
        results["started_at"] = utcnow()
        results["last_updated"] = utcnow()
        save_results(expert_id, results)
        session["started_at"] = results["started_at"]
        return redirect(url_for("section_intro", sec_idx=0))
    else:
        flash("Welcome back! Resuming from where you left off.", "resume")
        session["started_at"] = results.get("started_at", utcnow())

    return compute_redirect(expert_id)


@app.route("/section/<int:sec_idx>/intro")
@login_required
def section_intro(sec_idx):
    if sec_idx < 0 or sec_idx >= N_SECTIONS:
        return redirect(url_for("study_complete"))
    sec = SECTIONS[sec_idx]
    task1_order = sec.get("task1_order", list(range(len(sec["images"]))))
    n_task1 = len(task1_order)
    n_pairs = get_n_groups(sec)
    expert_id = session["expert_id"]
    results = load_results(expert_id)
    sec_data = results.get("sections", {}).get(str(sec_idx), {})
    locked = sec_data.get("locked", False)
    task1_locked = sec_data.get("task1_locked", False)
    task2_locked = sec_data.get("task2_locked", sec_idx in (4, 5, 8, 9)) or locked
    override_ids = sec_data.get("task1_override_ids", [])
    annotations = sec_data.get("annotations", {})
    pending_overrides = (locked or task1_locked) and any(
        annotations.get(oid, {}).get("task1") is None for oid in override_ids
    )
    sec_cfg = SECTIONS[sec_idx]
    group_size = sec_cfg.get("group_size", 2)
    n_groups = get_n_groups(sec_cfg)
    task2_done = sum(
        1 for pair_idx in range(n_groups)
        if all(
            annotations.get(sec_cfg["images"][pair_idx * group_size + offset]["img_id"], {}).get("task2") is not None
            for offset in [0, group_size - 1]
        )
    )
    # Find first unannotated T1 image so "Start Task 1" resumes correctly
    resume_img_idx = 0
    task1_complete = False
    if not task1_locked:
        images = sec_cfg["images"]
        for i, raw_idx in enumerate(task1_order):
            if annotations.get(images[raw_idx]["img_id"], {}).get("task1") is None:
                resume_img_idx = i
                break
        else:
            resume_img_idx = 0  # all done — start from beginning for review
            task1_complete = True
    return render_template("section_intro.html", sec=sec, sec_idx=sec_idx, n_sections=N_SECTIONS,
                           n_task1=n_task1, n_pairs=n_pairs, locked=locked,
                           task1_locked=task1_locked, task2_locked=task2_locked,
                           task2_done=task2_done, pending_overrides=pending_overrides,
                           resume_img_idx=resume_img_idx, task1_complete=task1_complete)


@app.route("/section/<int:sec_idx>/task1/<int:img_idx>", methods=["GET", "POST"])
@login_required
def task1(sec_idx, img_idx):
    if sec_idx < 0 or sec_idx >= N_SECTIONS:
        return redirect(url_for("study_complete"))
    sec = SECTIONS[sec_idx]
    images = sec["images"]
    # Use fixed shuffled order if present (prevents same-patient tiles in a row)
    task1_order = sec.get("task1_order", list(range(len(images))))
    total = len(task1_order)
    if img_idx < 0 or img_idx >= total:
        return redirect(url_for("task1_complete", sec_idx=sec_idx))

    img = images[task1_order[img_idx]]
    expert_id = session["expert_id"]

    if request.method == "POST":
        # Reject submissions for locked sections (unless this image is in the override list)
        results_check = load_results(expert_id)
        sec_state = results_check.get("sections", {}).get(str(sec_idx), {})
        override_ids = sec_state.get("task1_override_ids", [])
        if (sec_state.get("locked") or sec_state.get("task1_locked")) and img["img_id"] not in override_ids:
            return redirect(url_for("task1", sec_idx=sec_idx, img_idx=img_idx))

        rating = request.form.get("rating")
        if rating not in ("real", "synthetic"):
            return redirect(url_for("task1", sec_idx=sec_idx, img_idx=img_idx))

        results = load_results(expert_id)
        sec_data = ensure_section(results, sec_idx)
        ann = ensure_annotation(sec_data, img["img_id"])
        ann["task1"] = {"rating": rating, "rated_at": utcnow()}

        if sec_data["task1_started_at"] is None:
            sec_data["task1_started_at"] = utcnow()

        all_done = all(
            sec_data["annotations"].get(images[raw_idx]["img_id"], {}).get("task1") is not None
            for raw_idx in task1_order
        )
        if all_done:
            sec_data["task1_completed_at"] = utcnow()

        save_results(expert_id, results)

        next_idx = img_idx + 1
        if next_idx < total:
            return redirect(url_for("task1", sec_idx=sec_idx, img_idx=next_idx))
        else:
            return redirect(url_for("task1_complete", sec_idx=sec_idx))

    # GET — always use the blinded position-based URL so img_id is never exposed
    image_url = url_for("task1_image", sec_idx=sec_idx, img_idx=img_idx)
    next_image_url = url_for("task1_image", sec_idx=sec_idx, img_idx=img_idx + 1) if img_idx + 1 < total else None

    results = load_results(expert_id)
    sec_data = results.get("sections", {}).get(str(sec_idx), {})
    locked = sec_data.get("locked", False) or sec_data.get("task1_locked", False)
    override_ids = sec_data.get("task1_override_ids", [])
    is_override = img["img_id"] in override_ids
    existing_rating = sec_data.get("annotations", {}).get(img["img_id"], {}).get("task1", {})
    existing_rating = existing_rating.get("rating") if isinstance(existing_rating, dict) else None

    return render_template(
        "task1.html",
        sec=sec,
        img=img,
        img_idx=img_idx,
        total_images=total,
        sec_idx=sec_idx,
        n_sections=N_SECTIONS,
        image_url=image_url,
        next_image_url=next_image_url,
        overall_pct=overall_pct(expert_id),
        locked=locked and not is_override,
        is_override=is_override,
        existing_rating=existing_rating,
    )


@app.route("/section/<int:sec_idx>/task1_complete")
@login_required
def task1_complete(sec_idx):
    if sec_idx < 0 or sec_idx >= N_SECTIONS:
        return redirect(url_for("study_complete"))
    sec = SECTIONS[sec_idx]
    task1_order = sec.get("task1_order", list(range(len(sec["images"]))))
    n_images = len(task1_order)
    n_pairs = get_n_groups(sec)
    results = load_results(session["expert_id"])
    sec_data = results.get("sections", {}).get(str(sec_idx), {})
    task2_locked = (
        sec_data.get("task2_locked", sec_idx in (4, 5, 8, 9))
        or sec_data.get("locked", False)
    )
    return render_template(
        "task1_complete.html",
        sec=sec,
        sec_idx=sec_idx,
        n_images=n_images,
        n_pairs=n_pairs,
        n_sections=N_SECTIONS,
        task2_locked=task2_locked,
    )


@app.route("/section/<int:sec_idx>/task2/<int:pair_idx>", methods=["GET", "POST"])
@login_required
def task2(sec_idx, pair_idx):
    if sec_idx < 0 or sec_idx >= N_SECTIONS:
        return redirect(url_for("study_complete"))
    sec = SECTIONS[sec_idx]
    images = sec["images"]
    group_size = sec.get("group_size", 2)
    n_groups = get_n_groups(sec)
    if pair_idx < 0 or pair_idx >= n_groups:
        return redirect(url_for("section_complete", sec_idx=sec_idx))

    group = images[pair_idx * group_size:(pair_idx + 1) * group_size]
    expert_id = session["expert_id"]

    if request.method == "POST":
        results = load_results(expert_id)
        # Reject submissions for locked sections
        sec_state = results.get("sections", {}).get(str(sec_idx), {})
        if sec_state.get("locked") or sec_state.get("task2_locked"):
            return redirect(url_for("task2", sec_idx=sec_idx, pair_idx=pair_idx))

        sec_data = ensure_section(results, sec_idx)

        if sec_data["task2_started_at"] is None:
            sec_data["task2_started_at"] = utcnow()

        last = len(group) - 1
        for i, img in enumerate(group):
            # Only leftmost and rightmost are annotated; intermediates get empty entry
            if i == 0 or i == last:
                selected = request.form.getlist(f"features_{i}")
                other_text = request.form.get(f"other_text_{i}", "").strip()
            else:
                selected, other_text = [], ""
            ann = ensure_annotation(sec_data, img["img_id"])
            ann["task2"] = {
                "features": selected,
                "other_text": other_text,
                "rated_at": utcnow(),
            }

        all_done = all(
            sec_data["annotations"].get(img["img_id"], {}).get("task2") is not None
            for img in images[:n_groups * group_size]
        )
        if all_done:
            sec_data["task2_completed_at"] = utcnow()

        save_results(expert_id, results)

        next_pair = pair_idx + 1
        if next_pair < n_groups:
            return redirect(url_for("task2", sec_idx=sec_idx, pair_idx=next_pair))
        else:
            return redirect(url_for("section_complete", sec_idx=sec_idx))

    # GET
    group_urls = [
        img.get("hf_url") or url_for("proxy_image", img_id=img["img_id"])
        for img in group
    ]

    results = load_results(expert_id)
    sec_data = results.get("sections", {}).get(str(sec_idx), {})
    annotations = sec_data.get("annotations", {})
    locked = sec_data.get("locked", False) or sec_data.get("task2_locked", False)
    existing = [
        annotations.get(img["img_id"], {}).get("task2")
        for img in group
    ]

    return render_template(
        "task2.html",
        sec=sec,
        pair_idx=pair_idx,
        n_pairs=n_groups,
        group=group,
        group_urls=group_urls,
        existing=existing,
        sec_idx=sec_idx,
        n_sections=N_SECTIONS,
        features=SECTION_FEATURES.get(sec_idx, MORPHOLOGICAL_FEATURES_DEFAULT),
        overall_pct=overall_pct(expert_id),
        locked=locked,
    )


@app.route("/section/<int:sec_idx>/complete")
@login_required
def section_complete(sec_idx):
    if sec_idx < 0 or sec_idx >= N_SECTIONS:
        return redirect(url_for("study_complete"))
    sec = SECTIONS[sec_idx]
    expert_id = session["expert_id"]

    # Build mini-summary: count Real/Synthetic for this section
    results = load_results(expert_id)
    annotations = results.get("sections", {}).get(str(sec_idx), {}).get("annotations", {})
    n_real = sum(1 for a in annotations.values() if a.get("task1", {}) and a["task1"].get("rating") == "real")
    n_synthetic = sum(1 for a in annotations.values() if a.get("task1", {}) and a["task1"].get("rating") == "synthetic")

    next_sec_idx = sec_idx + 1
    has_next = next_sec_idx < N_SECTIONS
    remaining_sections = [
        {"idx": i, "label": SECTIONS[i]["label"]}
        for i in range(next_sec_idx, N_SECTIONS)
    ]

    return render_template(
        "section_complete.html",
        sec=sec,
        sec_idx=sec_idx,
        n_sections=N_SECTIONS,
        n_real=n_real,
        n_synthetic=n_synthetic,
        has_next=has_next,
        next_sec_idx=next_sec_idx,
        remaining_sections=remaining_sections,
    )


@app.route("/section/<int:sec_idx>/skip", methods=["POST"])
@login_required
def skip_section(sec_idx):
    if sec_idx < 0 or sec_idx >= N_SECTIONS:
        return redirect(url_for("study_complete"))
    expert_id = session["expert_id"]
    results = load_results(expert_id)
    sec_data = ensure_section(results, sec_idx)
    sec_data["skipped"] = True
    sec_data["skipped_at"] = utcnow()
    save_results(expert_id, results)
    next_sec_idx = sec_idx + 1
    if next_sec_idx < N_SECTIONS:
        return redirect(url_for("section_intro", sec_idx=next_sec_idx))
    return redirect(url_for("study_complete"))


@app.route("/complete")
@login_required
def study_complete():
    expert_id = session["expert_id"]
    results = load_results(expert_id)

    # Build per-section summary
    summary = []
    for sec_idx, sec in enumerate(SECTIONS):
        annotations = results.get("sections", {}).get(str(sec_idx), {}).get("annotations", {})
        n_images = len(sec["images"])
        n_rated = sum(1 for a in annotations.values() if a.get("task1") is not None)
        n_real = sum(1 for a in annotations.values() if a.get("task1", {}) and a["task1"].get("rating") == "real")
        n_synthetic = n_rated - n_real
        summary.append({
            "label": sec["label"],
            "n_images": n_images,
            "n_rated": n_rated,
            "n_real": n_real,
            "n_synthetic": n_synthetic,
        })

    # Find sections that are incomplete and not locked/pre-filled
    sections_data = results.get("sections", {})
    incomplete = []
    for sec_idx, sec in enumerate(SECTIONS):
        sec_data = sections_data.get(str(sec_idx), {})
        if sec_data.get("locked") or sec_data.get("task1_locked"):
            continue
        task1_order = sec.get("task1_order", list(range(len(sec["images"]))))
        annotations = sec_data.get("annotations", {})
        task1_done = all(
            annotations.get(sec["images"][i]["img_id"], {}).get("task1") is not None
            for i in task1_order
        )
        task2_locked = sec_data.get("task2_locked", sec_idx in (4, 5, 8, 9))
        n_groups = get_n_groups(sec)
        group_size = sec.get("group_size", 2)
        task2_done = task2_locked or all(
            annotations.get(sec["images"][pair_idx * group_size + offset]["img_id"], {}).get("task2") is not None
            for pair_idx in range(n_groups)
            for offset in [0, group_size - 1]
        )
        if not task1_done or not task2_done:
            incomplete.append({
                "label": sec["label"],
                "t1": task1_done,
                "t2": task2_done,
            })

    return render_template(
        "study_complete.html",
        expert_id=expert_id,
        summary=summary,
        results_file=f"expert_{expert_id}.json",
        incomplete=incomplete,
    )


@app.route("/admin/results")
def admin_results():
    if not ADMIN_KEY or request.args.get("key") != ADMIN_KEY:
        return "Unauthorized", 403
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in os.listdir(RESULTS_DIR):
            if fname.endswith(".json"):
                zf.write(os.path.join(RESULTS_DIR, fname), fname)
    buf.seek(0)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True,
                     download_name=f"mopadi_results_{timestamp}.zip")


@app.route("/section/<int:sec_idx>/task1_image/<int:img_idx>")
@login_required
def task1_image(sec_idx, img_idx):
    """Blinded image serving for Task 1: URL reveals only position, never img_id or filename."""
    if sec_idx < 0 or sec_idx >= N_SECTIONS:
        return "Not found", 404
    sec = SECTIONS[sec_idx]
    images = sec["images"]
    task1_order = sec.get("task1_order", list(range(len(images))))
    if img_idx < 0 or img_idx >= len(task1_order):
        return "Not found", 404
    img = images[task1_order[img_idx]]
    # Prefer local path for serving (avoids leaking HF filename in redirect)
    local_path = img.get("local_path")
    if local_path and os.path.exists(local_path):
        return send_file(local_path, mimetype="image/png")
    hf_url = img.get("hf_url")
    if hf_url:
        return redirect(hf_url)
    return "Image not found", 404


@app.route("/proxy_image/<img_id>")
@login_required
def proxy_image(img_id):
    """Serve image by img_id — used for Task 2 only (labels not blinded there)."""
    img = IMG_INDEX.get(img_id)
    if img is None:
        return "Image not found", 404
    local_path = img.get("local_path")
    if not local_path or not os.path.exists(local_path):
        return "Local image file not found", 404
    return send_file(local_path, mimetype="image/png")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6080, debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
