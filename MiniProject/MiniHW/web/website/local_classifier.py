import json
import math
import os
import random
from io import BytesIO
from typing import List

from PIL import Image, ImageDraw, ImageFilter, ImageStat


class LocalCentroidImageClassifier:
    """
    Small offline image classifier.

    It is intentionally lightweight for this homework: at startup it creates a tiny synthetic
    training set, extracts numeric image features, learns one centroid per class, and at
    inference time classifies the uploaded image by distance to those learned centroids.
    """

    LABELS = [
        "red object",
        "green object",
        "blue object",
        "bright image",
        "dark image",
        "document or screenshot",
        "textured scene",
    ]

    def __init__(self):
        self.centroids = self._train_centroids()

    def classify(self, image_bytes: bytes) -> List[dict]:
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        features = self._features(image)

        distances = []
        for label, centroid in self.centroids.items():
            distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(features, centroid)))
            distances.append((label, distance))

        distances.sort(key=lambda item: item[1])
        top = distances[:3]

        # Convert distances to positive confidence-like scores.
        raw_scores = [1.0 / (distance + 1e-6) for _, distance in top]
        total = sum(raw_scores) or 1.0
        scores = [(score / total) * 0.99 for score in raw_scores]

        matches = []
        for (label, _), score in zip(top, scores):
            # Always keep score in the required range: 0.0 < score <= 1.0.
            matches.append({"name": label, "score": round(max(min(score, 0.99), 0.001), 4)})

        # Rounding can make the sum slightly above 1. Keep it safely below 1.
        score_sum = sum(item["score"] for item in matches)
        if score_sum > 1.0:
            matches[-1]["score"] = round(matches[-1]["score"] - (score_sum - 0.999), 4)

        return matches

    def _train_centroids(self) -> dict:
        random.seed(7)
        samples = {label: [] for label in self.LABELS}
        for label in self.LABELS:
            for i in range(16):
                image = self._make_synthetic_image(label, i)
                samples[label].append(self._features(image))

        centroids = {}
        for label, vectors in samples.items():
            dimension = len(vectors[0])
            centroids[label] = [sum(vector[i] for vector in vectors) / len(vectors) for i in range(dimension)]
        return centroids

    def _make_synthetic_image(self, label: str, index: int) -> Image.Image:
        image = Image.new("RGB", (96, 96), "white")
        draw = ImageDraw.Draw(image)

        if label == "red object":
            bg = (235, 220, 215)
            fg = (210, 45 + index % 20, 35)
        elif label == "green object":
            bg = (220, 235, 220)
            fg = (45, 180, 65 + index % 20)
        elif label == "blue object":
            bg = (220, 228, 240)
            fg = (50, 80, 210)
        elif label == "bright image":
            bg = (245, 245, 235)
            fg = (255, 255, 210)
        elif label == "dark image":
            bg = (25, 25, 35)
            fg = (55, 55, 80)
        elif label == "document or screenshot":
            bg = (250, 250, 250)
            fg = (30, 30, 30)
        else:
            bg = (120, 110, 95)
            fg = (160, 145, 105)

        draw.rectangle([0, 0, 96, 96], fill=bg)

        if label == "document or screenshot":
            for y in range(12, 86, 10):
                draw.rectangle([10, y, 82 - (y % 17), y + 3], fill=fg)
        elif label == "textured scene":
            for _ in range(80):
                x = random.randint(0, 95)
                y = random.randint(0, 95)
                r = random.randint(1, 4)
                color = tuple(max(0, min(255, c + random.randint(-35, 35))) for c in fg)
                draw.ellipse([x, y, x + r, y + r], fill=color)
        else:
            margin = 16 + (index % 7)
            draw.ellipse([margin, margin, 96 - margin, 96 - margin], fill=fg)

        return image

    def _features(self, image: Image.Image) -> list:
        image = image.resize((96, 96)).convert("RGB")
        stat = ImageStat.Stat(image)
        mean_r, mean_g, mean_b = [value / 255.0 for value in stat.mean]
        std_r, std_g, std_b = [value / 255.0 for value in stat.stddev]

        gray = image.convert("L")
        gray_stat = ImageStat.Stat(gray)
        brightness = gray_stat.mean[0] / 255.0
        contrast = gray_stat.stddev[0] / 255.0

        # A simple edge-density feature.
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_mean = ImageStat.Stat(edges).mean[0] / 255.0

        max_c = max(mean_r, mean_g, mean_b)
        min_c = min(mean_r, mean_g, mean_b)
        saturation = max_c - min_c

        return [
            mean_r,
            mean_g,
            mean_b,
            std_r,
            std_g,
            std_b,
            brightness,
            contrast,
            edge_mean,
            saturation,
        ]


_LOCAL_MODEL = LocalCentroidImageClassifier()


def classify_locally(image_bytes: bytes) -> List[dict]:
    return _LOCAL_MODEL.classify(image_bytes)


def classify_with_gemini_if_configured(image_bytes: bytes, mime_type: str):
    """
    Uses Gemini only when GEMINI_API_KEY exists. If Gemini is unavailable or returns
    unexpected text, the caller can safely fall back to the local model.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        prompt = (
            "Classify this image. Return ONLY valid JSON exactly in this shape: "
            "{\"matches\":[{\"name\":\"label\",\"score\":0.8}]} . "
            "Return 1 to 3 matches. Every score must be > 0 and <= 1, and the sum must be <= 1."
        )

        response = client.models.generate_content(
            model=model_name,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt,
            ],
        )
        text = (getattr(response, "text", "") or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.replace("json", "", 1).strip()

        parsed = json.loads(text)
        matches = parsed.get("matches")
        if _valid_matches(matches):
            return matches
    except Exception:
        return None

    return None


def _valid_matches(matches) -> bool:
    if not isinstance(matches, list) or not matches:
        return False
    total = 0.0
    for match in matches:
        if not isinstance(match, dict):
            return False
        if not isinstance(match.get("name"), str) or not match["name"].strip():
            return False
        score = match.get("score")
        if not isinstance(score, (int, float)):
            return False
        if score <= 0.0 or score > 1.0:
            return False
        total += float(score)
    return 0.0 < total <= 1.0


def classify_image(image_bytes: bytes, mime_type: str) -> List[dict]:
    gemini_matches = classify_with_gemini_if_configured(image_bytes, mime_type)
    if gemini_matches:
        return gemini_matches
    return classify_locally(image_bytes)
