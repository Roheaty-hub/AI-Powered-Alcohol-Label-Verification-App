"""HTTP routes: the single page UI plus a small JSON API."""
from __future__ import annotations

import csv
from pathlib import Path

from flask import Blueprint, Response, jsonify, render_template, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

from app import batch
from app.models import ApplicationData
from app.pipeline.preprocess import ImageDecodeError
from app.pipeline.verify import verify_label

bp = Blueprint("main", __name__)

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
MAX_IMAGE_BYTES = 15 * 1024 * 1024
SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples"


def _error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _allowed(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in ALLOWED_EXT


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/api/health")
def health():
    return {"status": "ok"}


@bp.post("/api/verify")
def verify():
    file = request.files.get("image")
    if not file or not file.filename:
        return _error("Please choose a label image to check.")
    if not _allowed(file.filename):
        return _error("That file type isn't supported. Please upload a JPG or PNG image.")
    data = file.read()
    if not data:
        return _error("The uploaded file is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        return _error("That image is too large (15 MB max).")

    app_data = ApplicationData.from_mapping(request.form)
    try:
        report = verify_label(data, app_data)
    except ImageDecodeError as e:
        return _error(str(e))
    except RuntimeError:  # pytesseract raises RuntimeError on timeout
        return _error("Reading this label took too long. Try a smaller or clearer image.", 504)
    return jsonify(report.to_dict())


@bp.post("/api/batch")
def batch_start():
    manifest_file = request.files.get("manifest")
    images = [f for f in request.files.getlist("images") if f and f.filename]
    if not manifest_file or not manifest_file.filename:
        return _error("Please add the application data CSV.")
    if not images:
        return _error("Please add at least one label image.")
    try:
        manifest = batch.parse_manifest(manifest_file.read())
    except batch.ManifestError as e:
        return _error(str(e))

    files, skipped = [], []
    for f in images:
        name = Path(f.filename).name
        if _allowed(name):
            files.append((name, f.read()))
        else:
            skipped.append(name)
    job = batch.submit(files, manifest)
    return jsonify({"id": job.id, "total": len(job.items), "skipped": skipped}), 202


@bp.get("/api/batch/<job_id>")
def batch_status(job_id: str):
    job = batch.get(job_id)
    if job is None:
        return _error("Batch not found (results are kept for one hour).", 404)
    return jsonify(job.to_dict())


@bp.get("/api/batch/<job_id>/results.csv")
def batch_csv(job_id: str):
    job = batch.get(job_id)
    if job is None:
        return _error("Batch not found (results are kept for one hour).", 404)
    return Response(batch.results_csv(job), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=label-results-{job_id}.csv"})


@bp.get("/api/batch-template.csv")
def batch_template():
    return Response(batch.template_csv(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=application-data-template.csv"})


@bp.get("/api/samples")
def samples():
    """Bundled test labels with their application data, for the 'Try an example' picker."""
    path = SAMPLES_DIR / "batch_manifest.csv"
    if not path.exists():
        return jsonify([])
    with path.open(encoding="utf-8") as f:
        return jsonify(list(csv.DictReader(f)))


@bp.get("/samples/<path:name>")
def sample_file(name: str):
    """Serve the bundled test labels so evaluators can try the app without making their own."""
    return send_from_directory(SAMPLES_DIR, name)


@bp.app_errorhandler(RequestEntityTooLarge)
def too_large(_e):
    return _error("Upload is too large. Try splitting the batch into smaller groups.", 413)
