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


def _robust_line(xs: np.ndarray, ys: np.ndarray) -> tuple:
    """Theil–Sen 简化版直线拟合：随机点对斜率取中位数，
    抗局部凹陷（封面浅色边缘）和噪点。返回 (斜率, 截距, 中位残差)。"""
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


def _fit_quad_mask(content: np.ndarray, h: int, w: int):
    """把书轮廓拟合成四边形（四条边各拟合一条直线，取半平面交集），
    再整体内收，切掉边缘全部白色过渡像素。拟合不像四边形时返回 None。"""
    cols_any = content.any(axis=0)
    rows_any = content.any(axis=1)
    xs = np.where(cols_any)[0]
    ys = np.where(rows_any)[0]
    if len(xs) < w * 0.5 or len(ys) < h * 0.5:
        return None

    # 掐掉两端 4%：角部的圆角/缺口不参与直线拟合
    def trim(idx):
        k = max(2, int(len(idx) * 0.04))
        return idx[k:-k]

    xs_t, ys_t = trim(xs), trim(ys)
    first_r = content.argmax(axis=0)
    last_r = h - 1 - content[::-1, :].argmax(axis=0)
    first_c = content.argmax(axis=1)
    last_c = w - 1 - content[:, ::-1].argmax(axis=1)

    fits = []
    max_resid = max(3.0, min(h, w) * 0.01)
    for dx, dy in ((xs_t, first_r[xs_t]), (xs_t, last_r[xs_t]),
                   (ys_t, first_c[ys_t]), (ys_t, last_c[ys_t])):
        mm, bb, resid = _robust_line(dx, dy)
        if resid > max_resid:   # 这条边不直 → 不是规矩的四边形
            return None
        fits.append((mm, bb))

    (mt, bt), (mb_, bb_), (ml, bl), (mr, br) = fits
    inset = max(3, int(min(h, w) * 0.006))   # 内收量随图片分辨率走
    X = np.arange(w)[None, :]
    Y = np.arange(h)[:, None]
    mask = ((Y >= mt * X + bt + inset) & (Y <= mb_ * X + bb_ - inset) &
            (X >= ml * Y + bl + inset) & (X <= mr * Y + br - inset))
    if mask.mean() < 0.5:   # 交集面积异常小 → 拟合失败
        return None
    return mask


def _span_bool(content: np.ndarray, h: int, w: int) -> np.ndarray:
    """行/列跨度填充取交集（贴合任意凸形轮廓），返回 bool 数组。"""
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

    return row_span & col_span


def build_book_mask(img: Image.Image) -> Image.Image:
    """
    书主体轮廓 mask。实体书是长方体，正面拍摄的轮廓就是（近似）四边形：
    对上下左右四条边做抗噪直线拟合，取交集得到四边形，再整体内收几像素，
    把边缘的白色过渡像素（抗锯齿圈、浅色书页边、照明渐变）全部切掉——
    贴出来的边缘直接落在封面色块内，干净利落，无需描边遮丑。
    封面内部的白色区域必然在四边形内部，永远实心不穿帮。
    但书侧面（书脊/切口）透视下轮廓是"切了角的四边形"，纯直线在角部会
    越过实际边缘把白底圈进来 —— 所以四边形要再与跨度轮廓取交集：
    直边处内收后的四边形赢（切掉白色过渡），角部跨度轮廓赢（不越界）。
    轮廓不像四边形时（拟合残差大），退化为纯跨度填充。
    """
    content = _content_mask(img)

    # 3×3 开运算去掉背景上的孤立噪点，避免噪点带歪拟合
    m = Image.fromarray((content.astype(np.uint8)) * 255)
    m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    content = np.array(m) > 0
    h, w = content.shape

    final = _span_bool(content, h, w)
    quad = _fit_quad_mask(content, h, w)
    if quad is not None:
        final = final & quad

    mask = Image.fromarray((final.astype(np.uint8)) * 255)
    # 再往里收 1px，吃掉跨度轮廓段边缘最后一圈过渡像素
    return mask.filter(ImageFilter.MinFilter(3))


def draw_book_shadow(canvas: Image.Image, mask_r: Image.Image, px: int, py: int):
    """沿书的轮廓在其后方投双层影（四周均匀，不偏移）：
      - 宽柔影：大范围淡影，给画面层次
      - 缝隙线：紧贴边缘的深色窄影，像真实叠书的夹缝阴影，
        深色封面压深色封面时也能看出边界（分隔主要靠它）
    书底下的部分同时起接触投影作用。"""
    pad = 30          # 给模糊留的外扩空间
    big = Image.new('L', (mask_r.width + pad * 2, mask_r.height + pad * 2), 0)
    big.paste(mask_r, (pad, pad))

    soft = big.filter(ImageFilter.GaussianBlur(12)).point(lambda a: int(a * 0.35))
    canvas.paste(Image.new('RGB', soft.size, (60, 60, 60)), (px - pad, py - pad), soft)

    tight = big.filter(ImageFilter.GaussianBlur(3)).point(lambda a: int(a * 0.55))
    canvas.paste(Image.new('RGB', tight.size, (35, 35, 35)), (px - pad, py - pad), tight)


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

        # 按 z 顺序：轮廓柔影 → 书本体。四边形 mask 已把白色过渡像素切干净，
        # 边缘就是封面色块，不再需要描边；书与书的分隔靠影子
        draw_book_shadow(canvas, mask_r, px, py)
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
