import numpy as np
from PIL import Image, ImageDraw
from templates import TEMPLATES


def crop_whitespace(img: Image.Image, shrink: int = 1) -> Image.Image:
    """
    用"饱和度判定"裁掉书四周的白底 + 灰色投影/抗锯齿一圈，裁到书的彩色内容为止。
    这样实心叠压时前书边缘就是彩色，不会再有白边。书始终完整实心。

    判定一个像素是"背景"（白底或灰投影）的共同特征：又亮又无彩色（R≈G≈B）。
      - 背景/投影像素：min(R,G,B) ≥ 200 且 (max-min) ≤ 28  →  裁掉
      - 书的内容：要么有颜色(max-min>28)，要么够深(min<200) →  保留
    例：
      纯白(255,255,255)、灰投影(220,220,220) → 背景，裁掉 ✓
      浅蓝天空(180,210,240) min=180<200 → 内容，保留 ✓
      淡黄(250,250,210) 彩差40>28 → 内容，保留 ✓
      黑字(30,30,30) min=30<200 → 内容，保留 ✓

    注：书内部"标题与插画之间"的白区在外接框内部，不会被裁（只裁四周边缘）。
    """
    arr = np.array(img.convert('RGB')).astype(np.int16)
    mn = arr.min(axis=2)
    sat = arr.max(axis=2) - mn
    is_content = (mn < 200) | (sat > 28)

    # 每行/列内容像素占比 > 3% 才算"有书"，过滤掉稀疏的边缘投影
    row_frac = is_content.mean(axis=1)
    col_frac = is_content.mean(axis=0)
    rows = np.where(row_frac > 0.03)[0]
    cols = np.where(col_frac > 0.03)[0]
    if len(rows) == 0 or len(cols) == 0:
        raise ValueError("主体裁剪异常")

    r0, r1 = int(rows[0]), int(rows[-1])
    c0, c1 = int(cols[0]), int(cols[-1])

    # 再往里收 shrink 像素，吃掉最后一圈过渡像素
    sr0, sr1 = r0 + shrink, r1 - shrink
    sc0, sc1 = c0 + shrink, c1 - shrink
    if sr1 > sr0 and sc1 > sc0:
        r0, r1, c0, c1 = sr0, sr1, sc0, sc1

    cropped = img.crop((c0, r0, c1 + 1, r1 + 1))
    if cropped.width < 20 or cropped.height < 20:
        raise ValueError("主体裁剪异常")
    return cropped


def composite_books(book_images: list, n_books: int, debug: bool = False) -> Image.Image:
    template = TEMPLATES[n_books]
    canvas = Image.new('RGB', (800, 800), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    for slot, book in zip(sorted(template, key=lambda s: s['z']), book_images):
        bw, bh = book.size
        if bh == 0 or bw == 0:
            continue
        if 'scale_w' in slot:
            # 按宽度统一（同排/上下同宽用）；高度随比例，超 max_h 再回退按高度
            new_w = int(slot['scale_w'] * 800)
            new_h = int(bh * new_w / bw)
            max_h = slot.get('max_h', 800)
            if new_h > max_h:
                new_h = max_h
                new_w = int(bw * new_h / bh)
        else:
            # 按高度统一；太宽（正方形/横开本）回退按宽度，不霸占整行
            new_h = int(slot['scale_h'] * 800)
            new_w = int(bw * new_h / bh)
            max_w = slot['max_w']
            if new_w > max_w:
                new_w = max_w
                new_h = int(bh * new_w / bw)

        resized = book.resize((new_w, new_h), Image.LANCZOS).convert('RGB')
        cx = slot['cx']
        # 底边对齐：书底落在 baseline，同排书无论高矮都站在同一条线上
        px = cx - new_w // 2
        py = slot['baseline'] - new_h

        # 始终不透明粘贴 —— 书永远实心，绝不穿帮
        canvas.paste(resized, (px, py))

        if debug:
            draw.rectangle([px, py, px + new_w - 1, py + new_h - 1],
                           outline=(255, 0, 0), width=2)

    return canvas


def process_row(book_images: list, n_books: int, debug: bool = False) -> Image.Image:
    cropped = [crop_whitespace(img) for img in book_images]
    return composite_books(cropped, n_books, debug=debug)
