"""Batch processing (Janet's 200-300 label uploads).

Jobs run on a bounded thread pool and are tracked in memory. Images are held only
until they are processed, then dropped; results expire after JOB_TTL_S. Nothing is
written to disk. A production version would use a durable queue + worker service.
"""
from __future__ import annotations

import csv
import io
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.models import ApplicationData
from app.pipeline.preprocess import ImageDecodeError
from app.pipeline.verify import verify_label

MANIFEST_COLUMNS = ["filename", "brand_name", "class_type", "alcohol_content", "net_contents",
                    "bottler", "country_of_origin", "beverage_type"]
JOB_TTL_S = 60 * 60
WORKERS = int(os.environ.get("BATCH_WORKERS", max(2, (os.cpu_count() or 2))))

_pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="label")


class ManifestError(ValueError):
    pass


@dataclass
class BatchItem:
    filename: str
    status: str = "queued"        # queued | done | error
    result: dict | None = None
    error: str | None = None


@dataclass
class BatchJob:
    id: str
    items: list[BatchItem]
    created: float = field(default_factory=time.time)

    @property
    def completed(self) -> int:
        return sum(i.status != "queued" for i in self.items)

    def to_dict(self) -> dict:
        counts = {"pass": 0, "review": 0, "fail": 0, "error": 0}
        for i in self.items:
            if i.status == "error":
                counts["error"] += 1
            elif i.result:
                counts[i.result["overall"]] = counts.get(i.result["overall"], 0) + 1
        return {
            "id": self.id,
            "total": len(self.items),
            "completed": self.completed,
            "done": self.completed == len(self.items),
            "counts": counts,
            "items": [{"filename": i.filename, "status": i.status, "error": i.error, "result": i.result}
                      for i in self.items],
        }


_jobs: dict[str, BatchJob] = {}
_jobs_lock = threading.Lock()


def parse_manifest(data: bytes) -> dict[str, ApplicationData]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ManifestError("The application data file must be a UTF-8 CSV.") from e
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    if "filename" not in headers:
        raise ManifestError("The CSV needs a 'filename' column. Download the template to see the format.")
    rows: dict[str, ApplicationData] = {}
    for raw in reader:
        row = {(k or "").strip().lower(): (v or "") for k, v in raw.items()}
        name = row.get("filename", "").strip()
        if name:
            rows[name.lower()] = ApplicationData.from_mapping(row)
    if not rows:
        raise ManifestError("The CSV has no rows.")
    return rows


def _gc() -> None:
    cutoff = time.time() - JOB_TTL_S
    with _jobs_lock:
        for jid in [j for j, job in _jobs.items() if job.created < cutoff]:
            del _jobs[jid]


def _process(job: BatchJob, item: BatchItem, image: bytes, app: ApplicationData) -> None:
    try:
        item.result = verify_label(image, app).to_dict()
        item.status = "done"
    except ImageDecodeError as e:
        item.status, item.error = "error", str(e)
    except Exception:  # noqa: BLE001 — one bad file must not sink the batch
        item.status, item.error = "error", "Couldn't process this image."


def submit(files: list[tuple[str, bytes]], manifest: dict[str, ApplicationData]) -> BatchJob:
    _gc()
    items, work = [], []
    seen = set()
    for name, data in files:
        item = BatchItem(filename=name)
        items.append(item)
        seen.add(name.lower())
        app = manifest.get(name.lower())
        if app is None:
            item.status, item.error = "error", "No matching row in the application data CSV."
        else:
            work.append((item, data, app))
    for name in manifest:
        if name not in seen:
            items.append(BatchItem(filename=name, status="error", error="Listed in the CSV but no image uploaded."))

    job = BatchJob(id=uuid.uuid4().hex[:12], items=items)
    with _jobs_lock:
        _jobs[job.id] = job
    for item, data, app in work:
        _pool.submit(_process, job, item, data, app)
    return job


def get(job_id: str) -> BatchJob | None:
    return _jobs.get(job_id)


def results_csv(job: BatchJob) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["filename", "overall", "summary", "brand_name", "class_type", "alcohol_content",
                "net_contents", "bottler", "country_of_origin", "government_warning", "issues"])
    keys = ["brand_name", "class_type", "alcohol_content", "net_contents", "bottler",
            "country_of_origin", "government_warning"]
    for i in job.items:
        if i.status == "error" or not i.result:
            w.writerow([i.filename, "error", i.error or "Not processed", *[""] * len(keys), ""])
            continue
        by_field = {c["field"]: c for c in i.result["checks"]}
        issues = "; ".join(f"{c['label']}: {c['message']}" for c in i.result["checks"]
                           if c["status"] in ("fail", "review"))
        w.writerow([i.filename, i.result["overall"], i.result["summary"],
                    *[by_field.get(k, {}).get("status", "") for k in keys], issues])
    return out.getvalue()


def template_csv() -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(MANIFEST_COLUMNS)
    w.writerow(["label_001.jpg", "OLD TOM DISTILLERY", "Kentucky Straight Bourbon Whiskey",
                "45%", "750 mL", "Old Tom Distillery, Bardstown, Kentucky", "", "spirits"])
    return out.getvalue()
