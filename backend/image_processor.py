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


def _masks(img: Image.Image) -> tuple:
    """双阈值内容判定：
    strict：只认印刷内容（min<170 或 彩差>28）——排除白底、投影、书页浅色边
    loose ：只把纯白当背景（min<246 且 彩差≤10 为背景）——保住书页纸边。
    书页纸边（纸张厚度那条浅色高光）是实体书的物理边缘，叠压时它就是
    天然分界线；把它切掉封面画面会直接怼着封面画面 → "融合感"的真正根源。"""
    arr = np.array(img.convert('RGB')).astype(np.int16)
    mn = arr.min(axis=2)
    sat = arr.max(axis=2) - mn
    strict = (mn < 170) | (sat > 28)
    loose = (mn < 246) | (sat > 10)
    return strict, loose


def _denoise(content: np.ndarray) -> np.ndarray:
    """3×3 开运算去背景孤立噪点，避免带歪轮廓。"""
    m = Image.fromarray((content.astype(np.uint8)) * 255)
    m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    return np.array(m) > 0


def crop_whitespace(img: Image.Image, shrink: int = 1) -> Image.Image:
    """按严格内容外接框裁白边（独立工具函数；主流程 process_row
    改为先算 mask 再按 mask 外接框裁，避免这里把书页浅色边裁掉）。"""
    is_content, _ = _masks(img)

    # 每行/列内容像素占比 > 3% 才算"有书"，过滤掉稀疏的边缘投影
    row_frac = is_content.mean(axis=1)
    col_frac = is_content.mean(axis=0)
    rows = np.where(row_frac > 0.03)[0]
    cols = np.where(col_frac > 0.03)[0]
    if len(rows) == 0 or len(cols) == 0:
        raise ValueError("主体裁剪异常")

    r0, r1 = int(rows[0]), int(rows[-1])
    c0, c1 = int(cols[0]), int(cols[-1])

    sr0, sr1 = r0 + shrink, r1 - shrink
    sc0, sc1 = c0 + shrink, c1 - shrink
    if sr1 > sr0 and sc1 > sc0:
        r0, r1, c0, c1 = sr0, sr1, sc0, sc1

    cropped = img.crop((c0, r0, c1 + 1, r1 + 1))
    if cropped.width < 20 or cropped.height < 20:
        raise ValueError("主体裁剪异常")
    return cropped


def _robust_line(xs: np.ndarray, ys: np.ndarray) -> tuple:
    """Theil–Sen 简化版直线拟合：随机点对斜率取中位数，
    抗局部凹陷和噪点。返回 (斜率, 截距, 中位残差)。"""
    xs = xs.astype(np.float64)
    ys = ys.astype(np.float64)
    n = len(xs)
    if n < 20:
        return 0.0, float(np.median(ys)), 0.0
    rng = np.random.default_rng(0)
    i = rng.integers(0, n, 4000)
    j = rng.integers(0, n, 4000)
    span = xs[i] - xs[j]
    ok = np.abs(span) > (xs.max() - xs.min()) * 0.2
    m = float(np.median((ys[i][ok] - ys[j][ok]) / span[ok])) if ok.sum() >= 50 else 0.0
    b = float(np.median(ys - m * xs))
    resid = float(np.median(np.abs(ys - (m * xs + b))))
    return m, b, resid


def _edge_profiles(content: np.ndarray, h: int, w: int) -> tuple:
    top = content.argmax(axis=0)
    bottom = h - 1 - content[::-1, :].argmax(axis=0)
    left = content.argmax(axis=1)
    right = w - 1 - content[:, ::-1].argmax(axis=1)
    return top, bottom, left, right


def _fit_quad_mask(strict: np.ndarray, loose: np.ndarray, h: int, w: int):
    """实体书是长方体，正面拍摄的轮廓就是四边形——四条边各拟合一条直线。
    上/左/右边优先用宽松阈值的边界线（把书页浅色物理边保在书内，
    叠压时它就是天然分界线）；底边用严格线内收 2px（书底常有投影，必须切，
    而底边在版式里要么贴画布底、要么被前排书挡住，切一点不可见）。
    每条宽松线都有保护：偏离严格线超出容差（背景不干净）就退回严格线。
    轮廓不像四边形（残差大）返回 None。"""
    xs = np.where(strict.any(axis=0))[0]
    ys = np.where(strict.any(axis=1))[0]
    if len(xs) < 40 or len(ys) < 40:
        return None

    def trim(idx):
        k = max(2, int(len(idx) * 0.04))   # 掐掉两端 4%，角部不参与拟合
        return idx[k:-k]

    xs_t, ys_t = trim(xs), trim(ys)
    book_w, book_h = len(xs), len(ys)
    max_resid = max(3.0, min(book_w, book_h) * 0.01)

    s_top, s_bot, s_left, s_right = _edge_profiles(strict, h, w)
    l_top, _, l_left, l_right = _edge_profiles(loose, h, w)

    def fit(dx, dy):
        m, b, resid = _robust_line(dx, dy)
        return (m, b) if resid <= max_resid else None

    top_s = fit(xs_t, s_top[xs_t])
    bot_s = fit(xs_t, s_bot[xs_t])
    left_s = fit(ys_t, s_left[ys_t])
    right_s = fit(ys_t, s_right[ys_t])
    if not all((top_s, bot_s, left_s, right_s)):
        return None

    def pick(strict_line, loose_prof, idx, outward_sign, tol):
        """宽松线只允许比严格线向外 0~tol（书页边的合理厚度），
        否则退回严格线。outward_sign=+1 向外为更小值(上/左)，-1 为更大值(下/右)。"""
        lf = fit(idx, loose_prof[idx])
        if lf is None:
            return strict_line
        mid = float(idx[len(idx) // 2])
        d = ((strict_line[0] * mid + strict_line[1]) -
             (lf[0] * mid + lf[1])) * outward_sign
        return lf if -2 <= d <= tol else strict_line

    top = pick(top_s, l_top, xs_t, +1, book_h * 0.08)
    left = pick(left_s, l_left, ys_t, +1, book_w * 0.06)
    right = pick(right_s, l_right, ys_t, -1, book_w * 0.06)
    bot = (bot_s[0], bot_s[1] - 2)

    X = np.arange(w)[None, :]
    Y = np.arange(h)[:, None]
    quad = ((Y >= top[0] * X + top[1]) & (Y <= bot[0] * X + bot[1]) &
            (X >= left[0] * Y + left[1]) & (X <= right[0] * Y + right[1]))
    if quad.sum() < 0.5 * book_w * book_h:   # 面积异常 → 拟合失败
        return None
    return quad


def _smooth_profile(vals: np.ndarray, frac: float = 0.03) -> np.ndarray:
    """轮廓剖面滑动中值平滑：抹掉局部噪声的锯齿/波浪，
    保留宽度大于窗口的真实转折（切角）。"""
    n = len(vals)
    win = max(5, int(n * frac)) | 1
    if n < win:
        return vals
    padded = np.pad(vals, win // 2, mode='edge')
    sw = np.lib.stride_tricks.sliding_window_view(padded, win)
    return np.median(sw, axis=1).astype(vals.dtype)


def _span_bool(content: np.ndarray, h: int, w: int) -> np.ndarray:
    """行/列跨度填充取交集（贴合任意凸形轮廓），剖面先中值平滑。"""
    cols = np.arange(w)
    rows_any = content.any(axis=1)
    first_c = _smooth_profile(content.argmax(axis=1))
    last_c = _smooth_profile(w - 1 - content[:, ::-1].argmax(axis=1))
    row_span = rows_any[:, None] & (cols >= first_c[:, None]) & (cols <= last_c[:, None])

    rows = np.arange(h)[:, None]
    cols_any = content.any(axis=0)
    first_r = _smooth_profile(content.argmax(axis=0))
    last_r = _smooth_profile(h - 1 - content[::-1, :].argmax(axis=0))
    col_span = cols_any[None, :] & (rows >= first_r[None, :]) & (rows <= last_r[None, :])

    return row_span & col_span


def build_book_mask(img: Image.Image) -> Image.Image:
    """书主体轮廓 mask（在原图全幅上计算）：
    四边形（上/左/右宽松保书页边、底边严格切投影）∩ 宽松跨度轮廓（角部不越界）。
    封面内部的白色区域必然在四边形内部，永远实心不穿帮。
    拟合失败回退严格跨度轮廓（原行为）。"""
    strict, loose = _masks(img)
    strict = _denoise(strict)
    loose = _denoise(loose)
    h, w = strict.shape

    quad = _fit_quad_mask(strict, loose, h, w)
    if quad is not None:
        final = quad & _span_bool(loose, h, w)
        return Image.fromarray((final.astype(np.uint8)) * 255)

    final = _span_bool(strict, h, w)
    return Image.fromarray((final.astype(np.uint8)) * 255).filter(ImageFilter.MinFilter(3))


def draw_book_shadow(canvas: Image.Image, mask_r: Image.Image, px: int, py: int):
    """沿书的轮廓在其后方投一圈淡柔影（四周均匀，不偏移），只给画面层次感。
    书与书的分隔靠"书页物理边 + 硬直边 + 完全不透明"，
    不靠影子，也绝不画任何白/黑描边（用户均已否掉）。"""
    pad = 30
    big = Image.new('L', (mask_r.width + pad * 2, mask_r.height + pad * 2), 0)
    big.paste(mask_r, (pad, pad))
    soft = big.filter(ImageFilter.GaussianBlur(10)).point(lambda a: int(a * 0.40))
    canvas.paste(Image.new('RGB', soft.size, (55, 55, 55)), (px - pad, py - pad), soft)


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
        # mask 缩放后二值化：书是不透明实体，边缘必须 100% 实心——
        # 软边 alpha 会让前书边缘与后书颜色混在一起，也是"融合感"来源之一
        mask_r = mask.resize((new_w, new_h), Image.BILINEAR).point(lambda a: 255 if a >= 128 else 0)
        cx = slot['cx']
        # 底边对齐：书底落在 baseline，同排书无论高矮都站在同一条线上
        px = cx - new_w // 2
        py = slot['baseline'] - new_h

        draw_book_shadow(canvas, mask_r, px, py)
        canvas.paste(resized, (px, py), mask_r)

        if debug:
            draw.rectangle([px, py, px + new_w - 1, py + new_h - 1],
                           outline=(255, 0, 0), width=2)

    return canvas


def process_row(book_images: list, n_books: int, debug: bool = False) -> Image.Image:
    books = []
    for img in book_images:
        img = flatten_white(img)
        # 先在原图全幅上算 mask，再按 mask 外接框裁剪——
        # 若先按颜色裁剪会把书页浅色边裁掉，mask 再准也保不住物理边
        mask = build_book_mask(img)
        am = np.array(mask)
        rows = np.where(am.any(axis=1))[0]
        cols = np.where(am.any(axis=0))[0]
        if len(rows) < 20 or len(cols) < 20:
            raise ValueError("主体裁剪异常")
        box = (int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1)
        books.append((img.crop(box), mask.crop(box)))
    return composite_books(books, n_books, debug=debug)
