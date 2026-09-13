"""Pure, deterministic image-pixel analysis -- no AI/LLM call, no network
I/O. Every number here is computed directly from the actual thumbnail
pixels, reproducibly, with a cited/standard formula where one exists
(colorfulness is the Hasler-Süsstrunk metric). Never claims a CTR effect --
see docs comment in service.py for why.

Deliberately NOT implemented this pass (documented limitation, not a
silent gap): OCR-based text-amount/readability detection, and cross-
thumbnail similarity to competitors -- both need real image fetches
beyond the one thumbnail being analyzed and were judged too large to
build with the same rigor as the rest of this feature in one pass.
"""
import math
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageFilter

RECOMMENDED_MIN_WIDTH = 1280
RECOMMENDED_MIN_HEIGHT = 720
RECOMMENDED_ASPECT_RATIO = 16 / 9
_ASPECT_TOLERANCE = 0.05


@dataclass
class ThumbnailMetrics:
    width: int
    height: int
    meets_min_resolution: bool
    meets_aspect_ratio: bool
    contrast_score: float  # 0-100, higher = more separation between light/dark areas
    brightness_score: float  # 0-100, ~50 is a balanced mid-tone
    colorfulness_score: float  # 0-100, Hasler-Süsstrunk metric, normalized
    subject_prominence_score: float  # ~100 = center has as much visual detail as the frame average; higher = more concentrated


def load_image(image_bytes: bytes) -> Image.Image:
    return Image.open(BytesIO(image_bytes)).convert("RGB")


def _luminance_histogram_stats(img: Image.Image) -> tuple[float, float]:
    hist = img.convert("L").histogram()
    total = sum(hist)
    if total == 0:
        return 0.0, 0.0
    mean = sum(i * c for i, c in enumerate(hist)) / total
    variance = sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / total
    return mean, math.sqrt(variance)


def _resolution_metrics(img: Image.Image) -> tuple[int, int, bool, bool]:
    w, h = img.size
    meets_min_resolution = w >= RECOMMENDED_MIN_WIDTH and h >= RECOMMENDED_MIN_HEIGHT
    aspect = w / h if h else 0
    meets_aspect_ratio = abs(aspect - RECOMMENDED_ASPECT_RATIO) <= _ASPECT_TOLERANCE
    return w, h, meets_min_resolution, meets_aspect_ratio


def _contrast_score(img: Image.Image) -> float:
    _mean, stdev = _luminance_histogram_stats(img)
    # A stdev of ~90-100 on a 0-255 luminance range is already very high
    # contrast in practice; scaling by 100 keeps typical photos in a
    # readable ~20-70 band rather than clustering everything near 100.
    return round(min(100.0, stdev / 100 * 100), 1)


def _brightness_score(img: Image.Image) -> float:
    mean, _stdev = _luminance_histogram_stats(img)
    return round(mean / 255 * 100, 1)


def _colorfulness_score(img: Image.Image) -> float:
    """Hasler & Süsstrunk (2003) colorfulness metric, computed on a
    downsized copy for speed. Typical real photos land roughly in the
    0-100 raw range; not rescaled beyond clipping so the number stays
    tied to the published formula rather than an arbitrary curve."""
    small = img.resize((64, 64))
    pixels = list(small.getdata())
    n = len(pixels)
    if n == 0:
        return 0.0
    rg_vals = [r - g for r, g, _b in pixels]
    yb_vals = [0.5 * (r + g) - b for r, g, b in pixels]

    def mean_std(vals: list[float]) -> tuple[float, float]:
        m = sum(vals) / len(vals)
        var = sum((v - m) ** 2 for v in vals) / len(vals)
        return m, math.sqrt(var)

    rg_mean, rg_std = mean_std(rg_vals)
    yb_mean, yb_std = mean_std(yb_vals)
    std_root = math.sqrt(rg_std**2 + yb_std**2)
    mean_root = math.sqrt(rg_mean**2 + yb_mean**2)
    colorfulness = std_root + 0.3 * mean_root
    return round(min(100.0, colorfulness), 1)


def _subject_prominence_score(img: Image.Image) -> float:
    """Proxy for 'is there a clear, centered focal point': compares edge
    (visual-detail) density in the center half of the frame to the
    frame-wide average. This is a low-level heuristic, not subject/face
    detection -- it cannot tell WHAT the subject is, only whether visual
    complexity is concentrated centrally the way a prominent subject
    typically produces."""
    edges = img.convert("L").filter(ImageFilter.FIND_EDGES)
    w, h = edges.size
    if w < 4 or h < 4:
        return 100.0
    center = edges.crop((w // 4, h // 4, 3 * w // 4, 3 * h // 4))

    def mean_intensity(im: Image.Image) -> float:
        hist = im.histogram()
        total = sum(hist)
        return sum(i * c for i, c in enumerate(hist)) / total if total else 0.0

    full_mean = mean_intensity(edges)
    center_mean = mean_intensity(center)
    if full_mean == 0:
        return 100.0
    return round(min(300.0, (center_mean / full_mean) * 100), 1)


def analyze_thumbnail(image_bytes: bytes) -> ThumbnailMetrics:
    img = load_image(image_bytes)
    w, h, meets_res, meets_aspect = _resolution_metrics(img)
    return ThumbnailMetrics(
        width=w,
        height=h,
        meets_min_resolution=meets_res,
        meets_aspect_ratio=meets_aspect,
        contrast_score=_contrast_score(img),
        brightness_score=_brightness_score(img),
        colorfulness_score=_colorfulness_score(img),
        subject_prominence_score=_subject_prominence_score(img),
    )


def generate_recommendations(m: ThumbnailMetrics) -> list[str]:
    """Every recommendation cites the real measured number. Never claims a
    CTR/view effect -- these are structural/technical observations only,
    framed as heuristic best-practice guidance."""
    recs: list[str] = []
    if not m.meets_min_resolution:
        recs.append(
            f"Resolution is {m.width}x{m.height}, below YouTube's recommended "
            f"{RECOMMENDED_MIN_WIDTH}x{RECOMMENDED_MIN_HEIGHT} minimum -- may look soft on larger screens."
        )
    if not m.meets_aspect_ratio:
        recs.append(
            f"Aspect ratio is {m.width}:{m.height}, not the standard 16:9 -- "
            "YouTube may crop or letterbox this in some placements."
        )
    if m.contrast_score < 30:
        recs.append(
            f"Low contrast ({m.contrast_score}/100) -- increase separation between the subject "
            "and background so the thumbnail stays legible at small mobile sizes."
        )
    if m.brightness_score < 25:
        recs.append(
            f"Very dark thumbnail ({m.brightness_score}/100 brightness) -- may look like a near-black "
            "square in a mobile feed."
        )
    elif m.brightness_score > 90:
        recs.append(
            f"Very bright/washed-out thumbnail ({m.brightness_score}/100 brightness) -- "
            "detail may be lost at small sizes."
        )
    if m.colorfulness_score < 15:
        recs.append(
            f"Low colorfulness ({m.colorfulness_score}/100) -- flat/muted thumbnails can be harder "
            "to spot in a crowded feed (heuristic guidance, not a guaranteed effect on clicks)."
        )
    if m.subject_prominence_score < 90:
        recs.append(
            f"Visual detail is spread fairly evenly across the frame ({m.subject_prominence_score}/100 "
            "center-vs-frame ratio) rather than concentrated on a clear focal point -- "
            "consider a more centered, isolated subject."
        )
    return recs
