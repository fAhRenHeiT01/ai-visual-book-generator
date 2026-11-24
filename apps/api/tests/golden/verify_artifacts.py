"""Local browser/PDF parity gate shared by the scripted example browser suite."""

import base64
from io import BytesIO
import json
import sys

from PIL import Image
from pypdf import PdfReader
import pymupdf

from bookgen.adapters.pdf.playwright_exporter import image_ssim
from bookgen.config import load_settings


def verify(payload):
    data = base64.b64decode(payload["pdf"])
    reader = PdfReader(BytesIO(data))
    assert len(reader.pages) == payload["page_count"]
    text = " ".join(reader.pages[-1].extract_text().split())
    assert all(" ".join(source.split()) in text for source in payload["text"])
    settings = load_settings().export
    with pymupdf.open(stream=data, filetype="pdf") as document:
        pix = document[-1].get_pixmap(matrix=pymupdf.Matrix(96 / 72, 96 / 72), alpha=False)
        actual = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    expected = Image.open(BytesIO(base64.b64decode(payload["png"])))
    assert abs(actual.width - expected.width) <= 1 and abs(actual.height - expected.height) <= 1
    score = image_ssim(expected, actual.resize(expected.size))
    assert score >= settings.min_ssim, (score, settings.min_ssim)
    baseline_scores = []
    for pair in payload.get("baselines", []):
        images = [Image.open(BytesIO(base64.b64decode(encoded))) for encoded in pair]
        baseline_scores.append(image_ssim(*images))
    assert all(score >= settings.min_ssim for score in baseline_scores), baseline_scores
    return {"label": "Scripted fixture run", "case_id": payload["case_id"],
        "direction": payload["direction"], "pdf_ssim": score,
        "baseline_ssim": baseline_scores, "configured_minimum": settings.min_ssim,
        "physical_pages": len(reader.pages), "searchable_source_coverage": 1}


if __name__ == "__main__":
    print(json.dumps(verify(json.load(sys.stdin))))
