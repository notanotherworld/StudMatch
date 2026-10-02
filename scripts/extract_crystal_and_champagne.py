"""
Extract Telegram Crystal (Gem) and Champagne gift images from user-uploaded screenshots,
unblend Telegram background, make transparent, and export to web/static/webapp/gifts/.
"""
import os
import sys
import numpy as np
from PIL import Image

SOURCE_CRYSTAL = r"C:\Users\pokok\.gemini\antigravity\brain\993d070a-d2b6-4799-ac17-4edcbebfe132\.user_uploaded\media_1790803671149.png"
SOURCE_CHAMPAGNE = r"C:\Users\pokok\.gemini\antigravity\brain\993d070a-d2b6-4799-ac17-4edcbebfe132\.user_uploaded\media_1790803679224.png"
OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web", "static", "webapp", "gifts"))

BG_COLOR = np.array([23, 33, 43], dtype=np.float32)


def process_item(path, y1, y2, x1, x2, alpha_range=(3.0, 32.0)):
    im = Image.open(path).convert("RGB")
    arr = np.array(im)[y1:y2, x1:x2].astype(np.float32)
    dist = np.sqrt(((arr - BG_COLOR)**2).sum(axis=-1))

    t0, t1 = alpha_range
    alpha = np.clip((dist - t0) / (t1 - t0), 0.0, 1.0)
    alpha = alpha * alpha * (3.0 - 2.0 * alpha)

    unblended = np.zeros_like(arr)
    mask = alpha > 0.01
    denom = np.maximum(alpha[mask, None], 0.15)
    unblended[mask] = np.clip(BG_COLOR + (arr[mask] - BG_COLOR) / denom, 0.0, 255.0)
    unblended[~mask] = 0.0

    rgba = np.dstack([unblended, (alpha * 255.0)]).astype(np.uint8)

    ys, xs = np.where(rgba[:, :, 3] > 10)
    cropped_rgba = rgba[ys.min():ys.max()+1, xs.min():xs.max()+1]
    crop_im = Image.fromarray(cropped_rgba, "RGBA")

    w, h = crop_im.size
    scale = min(116.0 / w, 116.0 / h)
    new_w, new_h = int(round(w * scale)), int(round(h * scale))
    resized = crop_im.resize((new_w, new_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    paste_x = (128 - new_w) // 2
    paste_y = (128 - new_h) // 2
    canvas.paste(resized, (paste_x, paste_y), resized)
    return canvas


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    crystal = process_item(SOURCE_CRYSTAL, 40, 180, 20, 180)
    crystal.save(os.path.join(OUTPUT_DIR, "gift_gem.webp"), "WEBP", lossless=True)
    crystal.save(os.path.join(OUTPUT_DIR, "gift_diamond.webp"), "WEBP", lossless=True)

    champagne = process_item(SOURCE_CHAMPAGNE, 20, 180, 15, 180)
    champagne.save(os.path.join(OUTPUT_DIR, "gift_champagne.webp"), "WEBP", lossless=True)

    print("Successfully processed crystal and champagne gifts!")


if __name__ == "__main__":
    main()
