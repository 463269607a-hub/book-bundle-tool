import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from templates import TEMPLATES


def flatten_white(img: Image.Image) -> Image.Image:
    """带透明通道的图（PNG/WebP）先压到白底再处理，
    直接 convert('RGB') 会把透明区变黑，导致裁剪和轮廓全错。"""
    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        rgba = img.convert('RGBA')
        bg = Image.new('RGB', rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel('A'))
        return bg
    return img.convert('RGB')


def _content_mask(img: Image.Image) -> np.ndarray:
    """内容像素判定（与 crop_whitespace 同一套阈值）：
    背景/投影 = 又亮又无彩色（min≥200 且 彩差≤28），其余算书的内容。"""
    arr = np.array(img.convert('RGB')).astype(np.int16)
    mn = arr.min(axis=2)
    sat = arr.max(axis=2) - mn
    return (mn < 200) | (sat > 28)


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
    is_content = _content_mask(img)

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


def build_book_mask(img: Image.Image) -> Image.Image:
    """
    书主体轮廓 mask（跨度填充法），解决叠压时外接框残留白底压出白边的问题：
      - 每一行：从最左内容像素填到最右内容像素
      - 每一列：从最上内容像素填到最下内容像素
      - 取交集 → 贴合书形（含立体书斜边/圆角）的实心轮廓

    外接框内、书轮廓外的残留白底（尤其书顶上方两角）变透明；
    封面内部的白色区域左右上下都有内容包着，必然落在轮廓内，
    仍然实心不透明 —— 不会穿帮。
    """
    content = _content_mask(img)

    # 3×3 开运算去掉背景上的孤立噪点，避免噪点把跨度撑大
    m = Image.fromarray((content.astype(np.uint8)) * 255)
    m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    content = np.array(m) > 0

    h, w = content.shape
    cols = np.arange(w)
    rows_any = content.any(axis=1)
    first_c = content.argmax(axis=1)
    last_c = w - 1 - content[:, ::-1].argmax(axis=1)
    row_span = rows_any[:, None] & (cols >= first_c[:, None]) & (cols <= last_c[:, None])

    rows = np.arange(h)[:, None]
    cols_any = content.any(axis=0)
    first_r = content.argmax(axis=0)
    last_r = h - 1 - content[::-1, :].argmax(axis=0)
    col_span = cols_any[None, :] & (rows >= first_r[None, :]) & (rows <= last_r[None, :])

    mask = Image.fromarray(((row_span & col_span).astype(np.uint8)) * 255)
    # 再往里收 1px，吃掉轮廓边缘最后一圈发白的过渡像素
    return mask.filter(ImageFilter.MinFilter(3))


def draw_book_shadow(canvas: Image.Image, mask_r: Image.Image, px: int, py: int):
    """沿书的轮廓在其后方投一圈柔影（drop shadow）：
    叠压时前书边缘与后书之间有明暗分隔，一眼分得清哪本是哪本；
    书底下的部分同时起接触投影作用，让书"立"在画面上。"""
    pad = 18          # 给模糊留的外扩空间
    blur = 8
    off_x, off_y = 0, 3   # 影子略微下沉，像顶光照射
    big = Image.new('L', (mask_r.width + pad * 2, mask_r.height + pad * 2), 0)
    big.paste(mask_r, (pad, pad))
    big = big.filter(ImageFilter.GaussianBlur(blur)).point(lambda a: int(a * 0.5))
    dark = Image.new('RGB', big.size, (70, 70, 70))
    canvas.paste(dark, (px - pad + off_x, py - pad + off_y), big)


def composite_books(books: list, n_books: int, debug: bool = False) -> Image.Image:
    """books: [(书图, 轮廓mask), ...]"""
    template = TEMPLATES[n_books]
    canvas = Image.new('RGB', (800, 800), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    for slot, (book, mask) in zip(sorted(template, key=lambda s: s['z']), books):
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
        mask_r = mask.resize((new_w, new_h), Image.BILINEAR)
        cx = slot['cx']
        # 底边对齐：书底落在 baseline，同排书无论高矮都站在同一条线上
        px = cx - new_w // 2
        py = slot['baseline'] - new_h

        # 白色描边轮廓：mask 装进外扩画布再膨胀 4px（直接膨胀会被矩形边界截掉贴边处的描边）。
        # 深色压深色时灰影分不开，细白边保证任何配色下书与书边界都清晰；
        # 白底上描边不可见，只在叠压处生效
        ring_pad = 6
        ring = Image.new('L', (new_w + ring_pad * 2, new_h + ring_pad * 2), 0)
        ring.paste(mask_r, (ring_pad, ring_pad))
        ring = ring.filter(ImageFilter.MaxFilter(9))

        # 按 z 顺序：影子（沿描边外缘）→ 白描边 → 书本体
        draw_book_shadow(canvas, ring, px - ring_pad, py - ring_pad)
        canvas.paste(Image.new('RGB', ring.size, (255, 255, 255)),
                     (px - ring_pad, py - ring_pad), ring)
        # 按书形轮廓粘贴：轮廓内实心不穿帮，轮廓外残留白底不再压到后排书
        canvas.paste(resized, (px, py), mask_r)

        if debug:
            draw.rectangle([px, py, px + new_w - 1, py + new_h - 1],
                           outline=(255, 0, 0), width=2)

    return canvas


def process_row(book_images: list, n_books: int, debug: bool = False) -> Image.Image:
    books = []
    for img in book_images:
        cropped = crop_whitespace(flatten_white(img))
        books.append((cropped, build_book_mask(cropped)))
    return composite_books(books, n_books, debug=debug)
