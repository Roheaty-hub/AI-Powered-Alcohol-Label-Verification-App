"""Generate synthetic test labels + a batch manifest.

Each sample targets a scenario from the stakeholder interviews. Run:

    python scripts/generate_samples.py

Outputs PNG/JPG files and `batch_manifest.csv` into ./samples.
"""
from __future__ import annotations

import csv
import random
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.checks.warning import BODY  # noqa: E402

OUT = ROOT / "samples"
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


@dataclass
class Label:
    filename: str
    brand: str
    class_type: str
    abv_line: str
    net: str
    bottler: str
    warning_header: str = "GOVERNMENT WARNING:"
    warning_body: str = BODY
    header_bold: bool = True
    country: str = ""
    photo: bool = False
    # What the applicant typed on the form (the "application" side).
    application: dict = field(default_factory=dict)
    expected_outcome: str = ""


def draw_label(lb: Label) -> Image.Image:
    W, H = 1000, 1400
    img = Image.new("RGB", (W, H), (247, 241, 226))
    d = ImageDraw.Draw(img)
    d.rectangle([24, 24, W - 24, H - 24], outline=(70, 50, 30), width=6)

    def centered(y: int, text: str, f: ImageFont.FreeTypeFont, fill=(40, 28, 18)) -> int:
        w = d.textlength(text, font=f)
        d.text(((W - w) / 2, y), text, font=f, fill=fill)
        return y + f.size + 18

    y = 110
    brand_font = font("DejaVuSerif-Bold.ttf", 74)
    for line in textwrap.wrap(lb.brand, 16):
        y = centered(y, line, brand_font)
    y += 30
    d.line([200, y, W - 200, y], fill=(120, 80, 40), width=3)
    y += 50
    for line in textwrap.wrap(lb.class_type, 26):
        y = centered(y, line, font("DejaVuSerif.ttf", 46))
    y += 40
    y = centered(y, lb.abv_line, font("DejaVuSans-Bold.ttf", 42))
    y = centered(y, lb.net, font("DejaVuSans.ttf", 40))
    y += 30
    small = font("DejaVuSans.ttf", 26)
    for line in textwrap.wrap(lb.bottler, 52):
        y = centered(y, line, small)
    if lb.country:
        y = centered(y, lb.country, small)

    # Government warning block, left-aligned near the bottom.
    wf = font("DejaVuSans.ttf", 25)
    hf = font("DejaVuSans-Bold.ttf" if lb.header_bold else "DejaVuSans.ttf", 25)
    x0, y = 70, max(y + 40, 960)
    header_w = d.textlength(lb.warning_header + " ", font=hf)
    d.text((x0, y), lb.warning_header, font=hf, fill=(20, 20, 20))
    # First line continues after the header; wrap the rest.
    words = lb.warning_body.split()
    line, x, max_w = [], x0 + header_w, W - 70
    for wd in words:
        trial = " ".join(line + [wd])
        if x + d.textlength(trial, font=wf) > max_w:
            d.text((x, y), " ".join(line), font=wf, fill=(20, 20, 20))
            y += 34
            line, x = [wd], x0
        else:
            line.append(wd)
    d.text((x, y), " ".join(line), font=wf, fill=(20, 20, 20))
    return img


def photograph(img: Image.Image, seed: int = 7) -> Image.Image:
    """Simulate a phone photo: tilt, glare, blur, noise, background."""
    rnd = random.Random(seed)
    bg = Image.new("RGB", (img.width + 260, img.height + 260), (92, 84, 76))
    bg.paste(img, (130, 130))
    bg = bg.rotate(-5.5, resample=Image.BICUBIC, fillcolor=(92, 84, 76))

    glare = Image.new("L", bg.size, 0)
    gd = ImageDraw.Draw(glare)
    gd.ellipse([bg.width * 0.55, bg.height * 0.08, bg.width * 0.95, bg.height * 0.38], fill=150)
    glare = glare.filter(ImageFilter.GaussianBlur(90))
    bg = Image.composite(Image.new("RGB", bg.size, (255, 255, 250)), bg, glare)

    # Uneven lighting: darken toward the bottom-left.
    shade = Image.linear_gradient("L").rotate(35, expand=False).resize(bg.size).point(lambda v: int(v * 0.35))
    bg = Image.composite(Image.new("RGB", bg.size, (0, 0, 0)), bg, shade)

    bg = bg.filter(ImageFilter.GaussianBlur(1.1))
    px = bg.load()
    for _ in range(bg.width * bg.height // 25):
        x, y = rnd.randrange(bg.width), rnd.randrange(bg.height)
        r, g, b = px[x, y]
        n = rnd.randint(-28, 28)
        px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    return bg.resize((int(bg.width * 0.85), int(bg.height * 0.85)), Image.LANCZOS)


def app_for(lb: Label, **overrides) -> dict:
    base = {
        "brand_name": lb.brand,
        "class_type": lb.class_type,
        "alcohol_content": lb.abv_line,
        "net_contents": lb.net,
        "bottler": lb.bottler,
        "country_of_origin": lb.country,
        "beverage_type": "spirits",
    }
    base.update(overrides)
    return base


OLD_TOM = dict(
    brand="OLD TOM DISTILLERY",
    class_type="Kentucky Straight Bourbon Whiskey",
    abv_line="45% Alc./Vol. (90 Proof)",
    net="750 mL",
    bottler="Bottled by Old Tom Distillery, Bardstown, Kentucky",
)


def samples() -> list[Label]:
    labels: list[Label] = []

    lb = Label("01_old_tom_pass.png", **OLD_TOM, expected_outcome="pass")
    lb.application = app_for(lb)
    labels.append(lb)

    lb = Label("02_stones_throw_case_diff.png", brand="STONE'S THROW", class_type="London Dry Gin",
               abv_line="47% Alc./Vol. (94 Proof)", net="750 mL",
               bottler="Distilled and bottled by Stone's Throw Spirits, Portland, Oregon",
               expected_outcome="pass (brand differs only in case/punctuation)")
    lb.application = app_for(lb, brand_name="Stone’s Throw", alcohol_content="47%")
    labels.append(lb)

    lb = Label("03_warning_title_case.png", **OLD_TOM, warning_header="Government Warning:",
               expected_outcome="fail (warning heading not all caps)")
    lb.application = app_for(lb)
    labels.append(lb)

    lb = Label("04_wrong_abv.png", **{**OLD_TOM, "abv_line": "40% Alc./Vol. (80 Proof)"},
               expected_outcome="fail (label 40%, application 45%)")
    lb.application = app_for(lb, alcohol_content="45%")
    labels.append(lb)

    altered = BODY.replace("may cause health problems", "may cause minor health issues")
    lb = Label("05_warning_reworded.png", **OLD_TOM, warning_body=altered,
               expected_outcome="fail (warning wording altered)")
    lb.application = app_for(lb)
    labels.append(lb)

    lb = Label("06_header_not_bold.png", **OLD_TOM, header_bold=False,
               expected_outcome="review (warning heading not bold)")
    lb.application = app_for(lb)
    labels.append(lb)

    lb = Label("07_photo_tilt_glare.jpg", **OLD_TOM, photo=True,
               expected_outcome="pass or review (imperfect photo)")
    lb.application = app_for(lb)
    labels.append(lb)

    lb = Label("08_imported_beer_units.png", brand="HARBOR LIGHT", class_type="Pale Lager",
               abv_line="5.2% ALC/VOL", net="12 FL. OZ.",
               bottler="Imported by Harbor Light Imports, Seattle, Washington",
               country="Product of Mexico",
               expected_outcome="pass (application in mL, label in fl oz)")
    lb.application = app_for(lb, net_contents="355 mL", alcohol_content="5.2%",
                             beverage_type="beer", country_of_origin="Mexico")
    labels.append(lb)

    lb = Label("09_wrong_brand.png", **OLD_TOM, expected_outcome="fail (brand name mismatch)")
    lb.application = app_for(lb, brand_name="OLD TIMER DISTILLING CO")
    labels.append(lb)
    return labels


def main() -> None:
    OUT.mkdir(exist_ok=True)
    rows = []
    for lb in samples():
        img = draw_label(lb)
        if lb.photo:
            img = photograph(img)
            img.save(OUT / lb.filename, quality=82)
        else:
            img.save(OUT / lb.filename)
        rows.append({"filename": lb.filename, **lb.application, "expected_outcome": lb.expected_outcome})
        print("wrote", lb.filename)

    fields = ["filename", "brand_name", "class_type", "alcohol_content", "net_contents",
              "bottler", "country_of_origin", "beverage_type", "expected_outcome"]
    with open(OUT / "batch_manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print("wrote batch_manifest.csv")


if __name__ == "__main__":
    main()
