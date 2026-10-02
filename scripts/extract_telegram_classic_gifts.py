"""
Extract 9 classic Telegram gifts from user-provided screenshot and export them
as high-resolution, transparent, anti-aliased WebP assets into web/static/webapp/gifts/.
"""
import os
import sys
from PIL import Image, ImageDraw
import numpy as np
from scipy.ndimage import label, binary_dilation

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SOURCE_IMG_PATH = r"C:\Users\pokok\.gemini\antigravity\brain\993d070a-d2b6-4799-ac17-4edcbebfe132\.user_uploaded\media_1790801778051.png"
OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web", "static", "webapp", "gifts"))
SCRATCH_DIR = r"C:\Users\pokok\.gemini\antigravity\brain\993d070a-d2b6-4799-ac17-4edcbebfe132\scratch"

# Card bounding boxes in 702x1024 source screenshot
COL_SEGMENTS = [(13, 224), (245, 456), (479, 690)]
ROW_SEGMENTS = [(6, 330), (348, 672), (689, 1013)]

GIFT_GRID = [
    ["gift_heart", "gift_bear", "gift_box"],
    ["gift_rose", "gift_cake", "gift_bouquet"],
    ["gift_rocket", "gift_trophy", "gift_ring"]
]

BG_COLOR = np.array([23, 33, 43], dtype=np.float32)


def process_and_export_gifts():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(SCRATCH_DIR, exist_ok=True)

    print(f"Loading source image from {SOURCE_IMG_PATH}...")
    source_img = Image.open(SOURCE_IMG_PATH)
    arr = np.array(source_img)[:, :, :3]

    exported_files = []

    for r_idx in range(3):
        for c_idx in range(3):
            gift_name = GIFT_GRID[r_idx][c_idx]
            x1, x2 = COL_SEGMENTS[c_idx]
            y1, y2 = ROW_SEGMENTS[r_idx]
            card = arr[y1:y2+1, x1:x2+1].astype(np.float32)

            # Icon area within the 212x325 card
            patch = card[10:220, 10:202].copy()
            h, w, _ = patch.shape

            dist = np.sqrt(((patch - BG_COLOR)**2).sum(axis=-1))

            # Candidate background pixels
            cand_bg = dist <= 28.0

            # Label connected components of cand_bg
            labeled, num_features = label(cand_bg)

            # Find components touching the 4 image borders (external background)
            border_mask = np.zeros((h, w), dtype=bool)
            border_mask[0, :] = True
            border_mask[-1, :] = True
            border_mask[:, 0] = True
            border_mask[:, -1] = True

            touching_labels = set(np.unique(labeled[border_mask])) - {0}
            is_bg = np.isin(labeled, list(touching_labels))

            # Handle genuine internal holes for ring and trophy
            if gift_name == "gift_ring":
                # Center hole of the ring
                for lbl in range(1, num_features + 1):
                    if lbl not in touching_labels:
                        comp_size = (labeled == lbl).sum()
                        if comp_size > 1000:
                            is_bg |= (labeled == lbl)
            elif gift_name == "gift_trophy":
                # Handle holes inside the trophy handles
                for lbl in range(1, num_features + 1):
                    if lbl not in touching_labels:
                        comp_size = (labeled == lbl).sum()
                        if 100 < comp_size < 300:
                            is_bg |= (labeled == lbl)

            # Initial alpha: 0 where is_bg, 1 elsewhere
            alpha = np.where(is_bg, 0.0, 1.0)

            # Smooth anti-aliased edge along is_bg
            dilated_bg = binary_dilation(is_bg, iterations=2)
            edge_zone = dilated_bg & (~is_bg)

            t0, t1 = 5.0, 32.0
            edge_alpha = np.clip((dist[edge_zone] - t0) / (t1 - t0), 0.0, 1.0)
            edge_alpha = edge_alpha * edge_alpha * (3.0 - 2.0 * edge_alpha)
            alpha[edge_zone] = edge_alpha

            # Special treatment for cake: eliminate dark olive halo above candles
            if gift_name == "gift_cake":
                # Candle flames and wicks are around x centers ~ 65, 95.5, 126
                # in patch coordinates
                flame_xs = [65.0, 95.5, 126.0]
                for y in range(58):
                    for x in range(w):
                        r_val, g_val, b_val = patch[y, x]
                        is_flame = (r_val > 130 and g_val > 100 and b_val < 90)
                        is_wick = (y >= 48 and any(abs(x - cx) <= 3 for cx in flame_xs))
                        if not (is_flame or is_wick):
                            alpha[y, x] = 0.0

                # Between candles above y=70: ensure background is clear
                for y in range(58, 70):
                    for x in range(w):
                        if (76 <= x <= 85) or (107 <= x <= 115):
                            if dist[y, x] < 30:
                                alpha[y, x] = 0.0

            # Remove any tiny disconnected foreground specks (e.g. bouquet stray dot)
            fg_mask_raw = alpha > 0.05
            fg_labeled, fg_num = label(fg_mask_raw)
            for f_lbl in range(1, fg_num + 1):
                comp_size = (fg_labeled == f_lbl).sum()
                if comp_size < 15:
                    alpha[fg_labeled == f_lbl] = 0.0

            # Unmix RGB on edge pixels
            safe_alpha = np.maximum(alpha[:, :, None], 0.2)
            c_fg = np.clip(BG_COLOR + (patch - BG_COLOR) / safe_alpha, 0, 255)
            rgba = np.dstack([c_fg, alpha * 255]).astype(np.uint8)

            # Crop tight bounding box with 2px breathing margin
            fg_mask = rgba[:, :, 3] > 10
            y_indices = np.where(fg_mask.any(axis=1))[0]
            x_indices = np.where(fg_mask.any(axis=0))[0]

            y0, y1 = max(0, y_indices[0] - 2), min(h - 1, y_indices[-1] + 2)
            x0, x1 = max(0, x_indices[0] - 2), min(w - 1, x_indices[-1] + 2)

            cropped = rgba[y0:y1+1, x0:x1+1]
            item_img = Image.fromarray(cropped, "RGBA")

            # Scale to 128x128 with max dimension 116 (preserving 100% aspect ratio)
            cw, ch = item_img.size
            scale = 116.0 / max(cw, ch)
            nw, nh = int(round(cw * scale)), int(round(ch * scale))
            resized = item_img.resize((nw, nh), Image.Resampling.LANCZOS)

            canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
            paste_x = (128 - nw) // 2
            paste_y = (128 - nh) // 2
            canvas.paste(resized, (paste_x, paste_y), resized)

            target_file = os.path.join(OUTPUT_DIR, f"{gift_name}.webp")
            canvas.save(target_file, "WEBP", lossless=True)
            exported_files.append((gift_name, target_file, os.path.getsize(target_file)))
            print(f"  [OK] Exported {gift_name}.webp ({os.path.getsize(target_file)} bytes)")

    # Create composite preview sheet on both dark and light backgrounds
    print("\nGenerating composite verification preview...")
    cell_w, cell_h = 160, 160
    sheet_w = cell_w * 3 * 2 + 40
    sheet_h = cell_h * 3 + 60

    sheet = Image.new("RGB", (sheet_w, sheet_h), (15, 23, 42))
    draw = ImageDraw.Draw(sheet)

    left_x = 20
    right_x = left_x + cell_w * 3 + 20

    for r in range(3):
        for c in range(3):
            x_d = left_x + c * cell_w
            y_d = 40 + r * cell_h
            draw.rectangle([x_d+4, y_d+4, x_d+cell_w-4, y_d+cell_h-4], fill=(23, 33, 43), outline=(40, 52, 68), width=1)

            x_l = right_x + c * cell_w
            y_l = 40 + r * cell_h
            draw.rectangle([x_l+4, y_l+4, x_l+cell_w-4, y_l+cell_h-4], fill=(255, 255, 255), outline=(226, 232, 240), width=1)

    for r in range(3):
        for c in range(3):
            name = GIFT_GRID[r][c]
            item = Image.open(os.path.join(OUTPUT_DIR, f"{name}.webp"))

            x_d = left_x + c * cell_w + (cell_w - item.width) // 2
            y_d = 40 + r * cell_h + (cell_h - item.height) // 2
            sheet.paste(item, (x_d, y_d), item)

            x_l = right_x + c * cell_w + (cell_w - item.width) // 2
            y_l = 40 + r * cell_h + (cell_h - item.height) // 2
            sheet.paste(item, (x_l, y_l), item)

    preview_path = os.path.join(SCRATCH_DIR, "classic_gifts_final_preview.png")
    sheet.save(preview_path)
    print(f"Composite preview saved to: {preview_path}")

    return exported_files, preview_path


if __name__ == "__main__":
    process_and_export_gifts()
