# Decisions, assumptions & limitations

## Key decisions

**1. Local OCR (Tesseract) instead of a cloud vision/LLM API.**
Marcus said the network blocks outbound traffic to many domains and the previous vendor's ML features broke for exactly that reason. Sarah's 5-second limit rules out slow round-trips. Tesseract runs in the container in ~0.5 s per label with no outbound calls and no data leaving the boundary. Trade-off: a modern vision-language model would read stylized fonts and curved bottles better. The `Extractor` protocol in `app/pipeline/ocr.py` is the seam for adding one later (e.g. Azure OpenAI inside TTB's own tenant, which would sit inside their FedRAMP boundary).

**2. Deterministic rules for comparison, not an LLM judging "does this match?"**
Compliance decisions need to be explainable and repeatable. Every result says what was expected, what was read, and why. Fuzzy logic is confined to *reading* (OCR noise) and *formatting* (case/punctuation), never to substance — a wrong number or a reworded warning is always a Problem.

**3. Three-state results (Match / Check / Problem) instead of pass/fail.**
Dave's point: label review has nuance. Rather than force a binary that agents will distrust, uncertain cases go to "Check" with the reason shown. The tool's job is to clear routine matches fast and point agents at the rest.

**4. Python + Flask + vanilla JS, single container.**
Smallest stack that does the job. No frontend build, no database, no external services. Docker makes it portable to Azure (their platform) or any host.

**5. Batch via CSV manifest + background jobs + polling.**
300 labels can't finish in one HTTP request reliably, so uploads return a job ID and the UI polls. The CSV mirrors what an importer submission would contain and is matched to images by file name.

**6. Synthetic test labels generated in code.**
`scripts/generate_samples.py` renders labels for each interview scenario (title-case warning, reworded warning, non-bold header, wrong ABV, unit conversion, tilted/glary photo). Outcomes are encoded in `batch_manifest.csv` and asserted by the end-to-end tests.

## Assumptions

- The application data is entered by the agent (single) or provided as a CSV (batch); there is no COLA integration (per Marcus).
- One image per application containing all required statements. Real submissions often have front + back labels — see limitations.
- The warning body is compared case-insensitively; only the `GOVERNMENT WARNING:` header must be uppercase (per 27 CFR 16.22).
- Alcohol content is optional when beverage type is wine or beer; required for distilled spirits.
- Net contents within 1% (or 1 mL) are equal, so `12 FL OZ` matches `355 mL`.
- English labels only.

## Limitations

- **Bold detection is a heuristic.** Reliable on clean artwork; on soft photos it reports "couldn't confirm" rather than guessing. Never auto-fails.
- **Type size is not checked.** 27 CFR 16.22 sets minimum warning type sizes by container size; that needs physical dimensions the image doesn't provide.
- **Single image per application.** Front/back labels would need multiple images merged into one OCR text — a small extension to the API.
- **Heavily stylized fonts, curved text, and very low-resolution images** degrade Tesseract accuracy. The image-quality note flags these so the agent knows to look or request a new image.
- **Severe perspective distortion** (photos at steep angles) is only partially corrected — deskew handles rotation, not keystone.
- **Batch jobs live in memory** and are lost on restart; designed for one process. Fine for a prototype; a queue + worker pool is the production path.
- **No authentication.** Don't upload real application data to a public deployment.
- **Class/type is matched as text,** not validated against TTB's list of approved class/type designations.

## What I'd do next

1. Multi-image applications (front + back label).
2. Perspective correction (detect label quadrilateral → warp).
3. Pluggable second-opinion extractor (vision model in-tenant) used only when Tesseract confidence is low.
4. Validate class/type against the TTB designation list and beverage-type-specific mandatory fields (e.g. sulfite declaration for wine).
5. Usability test with Dave and Jenny; measure time-per-label vs. the manual baseline.
