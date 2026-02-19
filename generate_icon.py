"""Generate AccessDR icon: antenna + white cane merged symbol."""

from PIL import Image, ImageDraw
import math


def draw_icon(size: int) -> Image.Image:
    """Draw the AccessDR icon at the given pixel size."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size  # shorthand

    # Scaling factor relative to 256px base
    f = s / 256.0
    lw = max(1, round(8 * f))       # line width
    lw_thin = max(1, round(5 * f))  # thinner line

    # Background: rounded dark blue circle
    pad = round(8 * f)
    draw.ellipse(
        [pad, pad, s - pad, s - pad],
        fill=(25, 55, 110, 255),
    )

    # --- White Cane (bottom-left to centre, diagonal) ---
    # The cane goes from bottom-left up to the centre, angled ~60 deg
    cane_bottom_x = round(0.22 * s)
    cane_bottom_y = round(0.88 * s)
    cane_top_x = round(0.46 * s)
    cane_top_y = round(0.35 * s)

    # Cane shaft — white
    draw.line(
        [(cane_bottom_x, cane_bottom_y), (cane_top_x, cane_top_y)],
        fill=(255, 255, 255, 255),
        width=lw,
    )

    # Red tip at bottom of cane
    tip_len = round(0.08 * s)
    dx = cane_top_x - cane_bottom_x
    dy = cane_top_y - cane_bottom_y
    length = math.sqrt(dx * dx + dy * dy)
    ux, uy = dx / length, dy / length
    tip_end_x = round(cane_bottom_x + ux * tip_len)
    tip_end_y = round(cane_bottom_y + uy * tip_len)
    draw.line(
        [(cane_bottom_x, cane_bottom_y), (tip_end_x, tip_end_y)],
        fill=(220, 50, 50, 255),
        width=lw,
    )

    # Cane handle (small hook at top of cane)
    handle_r = round(0.04 * s)
    draw.arc(
        [cane_top_x - handle_r * 2, cane_top_y - handle_r,
         cane_top_x, cane_top_y + handle_r],
        start=180, end=360,
        fill=(255, 255, 255, 255),
        width=lw_thin,
    )

    # --- Antenna (extends upward from centre-right) ---
    ant_base_x = round(0.54 * s)
    ant_base_y = round(0.55 * s)
    ant_top_x = round(0.54 * s)
    ant_top_y = round(0.15 * s)

    # Antenna mast — white
    draw.line(
        [(ant_base_x, ant_base_y), (ant_top_x, ant_top_y)],
        fill=(255, 255, 255, 255),
        width=lw,
    )

    # Antenna tip — small circle
    tip_r = max(2, round(5 * f))
    draw.ellipse(
        [ant_top_x - tip_r, ant_top_y - tip_r,
         ant_top_x + tip_r, ant_top_y + tip_r],
        fill=(100, 200, 255, 255),
    )

    # Antenna base — small triangle/ground
    base_w = round(0.10 * s)
    base_h = round(0.05 * s)
    draw.polygon(
        [
            (ant_base_x, ant_base_y),
            (ant_base_x - base_w // 2, ant_base_y + base_h),
            (ant_base_x + base_w // 2, ant_base_y + base_h),
        ],
        fill=(255, 255, 255, 255),
    )

    # --- Signal waves (arcs emanating from antenna tip) ---
    wave_colour = (100, 200, 255, 200)
    wave_lw = max(1, round(3.5 * f))
    for i, radius in enumerate([round(0.10 * s), round(0.17 * s), round(0.24 * s)]):
        alpha = 200 - i * 50
        wc = (100, 200, 255, max(alpha, 80))
        bbox = [
            ant_top_x - radius, ant_top_y - radius,
            ant_top_x + radius, ant_top_y + radius,
        ]
        draw.arc(bbox, start=220, end=320, fill=wc, width=wave_lw)

    # --- Cross element: a small diagonal connecting cane to antenna ---
    # This visually ties the two symbols together
    cross_x1 = round(0.42 * s)
    cross_y1 = round(0.45 * s)
    cross_x2 = round(0.54 * s)
    cross_y2 = round(0.45 * s)
    draw.line(
        [(cross_x1, cross_y1), (cross_x2, cross_y2)],
        fill=(255, 255, 255, 180),
        width=max(1, round(3 * f)),
    )

    return img


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [draw_icon(sz) for sz in sizes]

    # Save as .ico with all sizes
    images[-1].save(
        "accessdr.ico",
        format="ICO",
        sizes=[(sz, sz) for sz in sizes],
        append_images=images[:-1],
    )
    print(f"Saved accessdr.ico with sizes: {sizes}")

    # Also save a 256px PNG for preview
    images[-1].save("accessdr_icon_preview.png")
    print("Saved accessdr_icon_preview.png for preview")


if __name__ == "__main__":
    main()
