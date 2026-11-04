"""Compose labeled contact sheet from (image_path, label) pairs."""
from PIL import Image, ImageDraw, ImageFont
def make_sheet(items, out, cols=8, tile_h=400):
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
    tiles = []
    for path, label in items:
        im = Image.open(path).convert("RGB")
        im = im.resize((round(im.width * tile_h / im.height), tile_h))
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, im.width, 30], fill=(0, 0, 0))
        d.text((5, 3), label, font=font, fill=(255, 255, 0))
        tiles.append(im)
    tw = max(t.width for t in tiles)
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + 4), rows * (tile_h + 4)), "white")
    for k, t in enumerate(tiles):
        sheet.paste(t, ((k % cols) * (tw + 4), (k // cols) * (tile_h + 4)))
    sheet.save(out, quality=82)
