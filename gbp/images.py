"""Images for Google Posts.

Two backends:

  chatgpt   Drives a Chrome you are ALREADY logged into, over the DevTools
            protocol -- the same approach as a Pinterest pin script. No API
            key, no per-image cost. Fragile by nature: it is a real web UI and
            the selectors move. Every step is logged and the browser is left
            open on failure so you can finish by hand.

  gemini    Google AI Studio's image model over HTTP. Needs GOOGLE_API_KEY.
            Free tier, stable, no browser. Use this on a server.

  none      Skip images. Posts still publish; they just have no picture.

WHERE AI IMAGES MAY AND MAY NOT GO
----------------------------------
These images are for GOOGLE POSTS only.

This module will not upload them to the profile's photo gallery, and there is
no flag to make it. Google's photo guidelines require that photos represent the
actual business, and a gallery of generated images is a well-known route to a
quality review and a suspension. A generated illustration on a weekly Post is
ordinary marketing; a generated "photo of our workshop" is a misrepresentation.

Real photos of real work always beat these. Use them when you have them.
"""
from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass
from pathlib import Path

from . import config

CDP_DEFAULT = "http://localhost:9222"

# Every ChatGPT selector in one place. When the UI moves, this is the only
# thing to fix. Each entry is tried in order.
SELECTORS = {
    "composer": [
        "#prompt-textarea",
        "div[contenteditable='true'][id='prompt-textarea']",
        "textarea[data-testid='prompt-textarea']",
        "div.ProseMirror[contenteditable='true']",
    ],
    "send": [
        "button[data-testid='send-button']",
        "button[aria-label='Send prompt']",
        "button[aria-label='Send message']",
    ],
    "image": [
        "div[data-testid^='conversation-turn'] img[src*='oaiusercontent']",
        "img[alt*='Generated']",
        "div.group\\/imagegen-image img",
        "main img[src^='https://']",
    ],
}

STYLE = (
    "Photorealistic editorial photograph, natural daylight, shallow depth of "
    "field, shot on a 35mm lens. Real-looking people and real working "
    "conditions, not stock-photo posing. No text, no logos, no watermarks, no "
    "captions anywhere in the image. Landscape orientation, 4:3."
)


@dataclass
class GeneratedImage:
    path: Path
    prompt: str
    backend: str


def build_prompt(service: str, city: str, extra: str = "") -> str:
    """Turn a service and a place into something worth looking at.

    Naming the city matters: it pulls in the local architecture, weather and
    light, which is what stops every post looking like the same stock library
    everyone else is using.
    """
    bits = [
        f"A {service.lower()} job in progress in {city}." if city
        else f"A {service.lower()} job in progress.",
        f"Show the setting typical of {city}: local building style, street and "
        f"weather." if city else "",
        extra.strip(),
        STYLE,
    ]
    return " ".join(b for b in bits if b)


def detail_from_page(page) -> str:
    """Turn a service page into a sentence of visual direction.

    A prompt that says "boiler repair" produces a generic stock scene. The same
    prompt plus what the page actually describes -- the equipment, the setting,
    the kind of property -- produces something that looks like this business's
    work rather than anyone's.

    Only nouns from the page are used. No claim is made in an image.
    """
    if page is None or not getattr(page, "ok", False):
        return ""
    bits: list[str] = []
    heading = getattr(page, "h1", "") or getattr(page, "title", "")
    if heading:
        bits.append(f"The work shown is: {heading}.")
    subs = [h for h in (getattr(page, "headings", []) or [])[:6] if len(h) < 70]
    if subs:
        bits.append("Include details suggesting: " + "; ".join(subs) + ".")
    return " ".join(bits)


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60] or "post"


def _out_path(name: str) -> Path:
    d = config.DATA_DIR / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{int(time.time())}-{_slug(name)}.png"


# ------------------------------------------------------------------- chatgpt

def _first(page, keys: list[str], timeout: int = 8000):
    """Try each selector in turn; return the first that appears."""
    last = None
    for sel in keys:
        try:
            el = page.wait_for_selector(sel, timeout=timeout, state="visible")
            if el:
                return el
        except Exception as exc:  # playwright TimeoutError and friends
            last = exc
            continue
    raise RuntimeError(
        "None of the known selectors matched. ChatGPT has probably changed its "
        "UI.\n  Fix the list in gbp/images.py SELECTORS -- it is the only place "
        f"they live.\n  Last error: {last}")


def via_chatgpt(prompt: str, name: str, cfg: dict) -> GeneratedImage:
    from playwright.sync_api import sync_playwright

    icfg = cfg.get("images", {}) or {}
    cdp = icfg.get("cdp", CDP_DEFAULT)
    wait_s = int(icfg.get("wait_seconds", 180))

    print(f"  [img] connecting to your Chrome on {cdp}")
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.connect_over_cdp(cdp)
        except Exception as exc:
            raise RuntimeError(
                f"Could not attach to Chrome on {cdp}.\n\n"
                "  Start Chrome with remote debugging first, log into ChatGPT in\n"
                "  it once, and leave it open:\n\n"
                '    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
                "--remote-debugging-port=9222 --user-data-dir=C:/gbp-chrome\n\n"
                f"  ({exc})") from exc

        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        try:
            page.goto("https://chatgpt.com/", wait_until="domcontentloaded",
                      timeout=60000)

            if "auth" in page.url or "login" in page.url:
                raise RuntimeError(
                    "That Chrome profile is not logged into ChatGPT.\n"
                    "  Log in by hand in this window, then run again.")

            print("  [img] typing the prompt")
            composer = _first(page, SELECTORS["composer"])
            composer.click()
            page.keyboard.insert_text(prompt)
            time.sleep(0.4)

            try:
                _first(page, SELECTORS["send"], timeout=4000).click()
            except RuntimeError:
                page.keyboard.press("Enter")

            print(f"  [img] waiting for the image (up to {wait_s}s)")
            deadline = time.time() + wait_s
            src = None
            while time.time() < deadline:
                for sel in SELECTORS["image"]:
                    try:
                        el = page.query_selector(sel)
                    except Exception:
                        continue
                    if not el:
                        continue
                    candidate = el.get_attribute("src") or ""
                    # Skip avatars and UI chrome, which are small and inline.
                    if candidate.startswith("http") and "oaiusercontent" in candidate:
                        src = candidate
                        break
                    if candidate.startswith("data:image"):
                        src = candidate
                        break
                if src:
                    break
                time.sleep(2)

            if not src:
                raise RuntimeError(
                    "No image appeared in time. The browser is still open -- "
                    "check whether ChatGPT asked something, hit a limit, or is "
                    "still drawing.")

            out = _out_path(name)
            if src.startswith("data:image"):
                out.write_bytes(base64.b64decode(src.split(",", 1)[1]))
            else:
                buf = ctx.request.get(src, timeout=60000).body()
                out.write_bytes(buf)

            print(f"  [img] saved {out.name} ({out.stat().st_size // 1024} KB)")
            page.close()
            return GeneratedImage(out, prompt, "chatgpt")

        except Exception:
            print("  [img] leaving the browser open so you can see what happened")
            raise


# -------------------------------------------------------------------- gemini

def via_gemini(prompt: str, name: str, cfg: dict) -> GeneratedImage:
    import requests

    key = config.env("GOOGLE_API_KEY", required=True)
    model = (cfg.get("images", {}) or {}).get(
        "gemini_model", "gemini-2.5-flash-image")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent")

    print(f"  [img] asking {model}")
    for attempt in range(4):
        resp = requests.post(
            url, params={"key": key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=180,
        )
        if resp.status_code == 429:
            wait = 5 * (attempt + 1)
            print(f"  [img] free-tier rate limit, waiting {wait}s")
            time.sleep(wait)
            continue
        if resp.status_code >= 300:
            raise RuntimeError(f"Image API returned {resp.status_code}: "
                               f"{resp.text[:300]}")
        data = resp.json()
        for cand in data.get("candidates", []):
            for part in (cand.get("content", {}) or {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    out = _out_path(name)
                    out.write_bytes(base64.b64decode(inline["data"]))
                    print(f"  [img] saved {out.name}")
                    return GeneratedImage(out, prompt, "gemini")
        raise RuntimeError("The image model replied with no image. "
                           "The prompt may have been refused.")
    raise RuntimeError("Rate limited four times in a row. Try again later.")


# ------------------------------------------------------------------- hosting

def host(image: GeneratedImage, cfg: dict) -> str | None:
    """Get the image to a public URL.

    Google Posts take a `sourceUrl`, not bytes. There is no endpoint to attach
    a local file to a post, so the image has to be reachable on the open web
    before the post can reference it. Two supported routes:

      imagekit   uploaded via the ImageKit API, returns a CDN url
      base_url   you sync data/images/ to your own web space, and we build the
                 url from the filename

    Note we do NOT route this through the profile's own photo library, even
    though that would be the easy path. See the warning at the top of this file.
    """
    icfg = cfg.get("images", {}) or {}
    mode = icfg.get("host", "none")

    if mode == "none":
        return None

    if mode == "base_url":
        base = (icfg.get("base_url") or "").rstrip("/")
        if not base:
            raise RuntimeError("images.host is 'base_url' but images.base_url "
                               "is empty in config.yaml.")
        print(f"  [img] copy {image.path} to your web space, then it is at:")
        print(f"        {base}/{image.path.name}")
        return f"{base}/{image.path.name}"

    if mode == "imagekit":
        import requests

        private = config.env("IMAGEKIT_PRIVATE_KEY", required=True)
        folder = icfg.get("imagekit_folder", "/gbp-posts")
        with open(image.path, "rb") as fh:
            resp = requests.post(
                "https://upload.imagekit.io/api/v1/files/upload",
                auth=(private, ""),
                files={"file": (image.path.name, fh, "image/png")},
                data={"fileName": image.path.name, "folder": folder,
                      "useUniqueFileName": "true"},
                timeout=120,
            )
        if resp.status_code >= 300:
            raise RuntimeError(f"ImageKit upload failed ({resp.status_code}): "
                               f"{resp.text[:300]}")
        url = resp.json().get("url")
        print(f"  [img] hosted at {url}")
        return url

    raise RuntimeError(f"Unknown images.host '{mode}'. "
                       f"Use imagekit, base_url or none.")


def generate(service: str, city: str, name: str, cfg: dict,
             extra: str = "") -> GeneratedImage | None:
    """Make one image for a post, or return None if images are switched off."""
    backend = (cfg.get("images", {}) or {}).get("backend", "none")
    if backend == "none":
        return None
    prompt = build_prompt(service, city, extra)
    if backend == "chatgpt":
        return via_chatgpt(prompt, name, cfg)
    if backend == "gemini":
        return via_gemini(prompt, name, cfg)
    raise RuntimeError(f"Unknown image backend '{backend}'. "
                       f"Use chatgpt, gemini or none.")
