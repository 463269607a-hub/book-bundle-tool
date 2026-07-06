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
    # 实测（用户真实图 2.jpg）：书页纸边亮度可达 249~254，背景是精确的 255 纯白，
    # loose 的背景判定必须收到"≥254 且无彩色"，否则最亮的纸边被当背景切掉 → 融合
    loose = (mn < 254) | (sat > 8)
    # 近白：书页纸边那种"发白无彩色"的像素（用于把白边整形成统一宽度）
    nw = (mn >= 228) & (sat <= 14)
    return strict, loose, nw


def _denoise(content: np.ndarray) -> np.ndarray:
    """3×3 开运算去背景孤立噪点，避免带歪轮廓。"""
    m = Image.fromarray((content.astype(np.uint8)) * 255)
    m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    return np.array(m) > 0


def crop_whitespace(img: Image.Image, shrink: int = 1) -> Image.Image:
    """按严格内容外接框裁白边（独立工具函数；主流程 process_row
    改为先算 mask 再按 mask 外接框裁，避免这里把书页浅色边裁掉）。"""
    is_content, _, _ = _masks(img)

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


def _seg_boundary(idx: np.ndarray, prof: np.ndarray, tol: float, envelope: float) -> tuple:
    """长方体的边 = 分段直线：先拟合主直线，小波动一律吸附到线上（横平竖直）；
    与主线同向偏差超过 tol 且足够长的连续段（书脊顶、透视产生的第二条边、
    切角/圆角）各自再拟合一条直线。返回 (idx 上的边界值, 对实际轮廓的中位残差)。"""
    raw = prof[idx].astype(np.float64)
    m, b, _ = _robust_line(idx, prof[idx])
    line = m * idx + b
    dev = raw - line
    big = np.abs(dev) > tol
    n = len(idx)
    min_seg = max(8, int(n * 0.04))

    # 找出各分段（含主线段），记录 (起, 止, 斜率, 截距)
    pieces = []
    main_start = 0
    i = 0
    while i < n:
        if not big[i]:
            i += 1
            continue
        j = i + 1
        while j < n and big[j] and (dev[j] > 0) == (dev[i] > 0):
            j += 1
        if j - i >= min_seg:
            sm, sb, _ = _robust_line(idx[i:j], prof[idx[i:j]])
            seg = sm * idx[i:j] + sb
            # 分段线不能离主线太远（防止把背景上的横向杂物当成边）
            if np.max(np.abs(seg - line[i:j])) <= envelope:
                if i > main_start:
                    pieces.append([main_start, i, m, b])
                pieces.append([i, j, sm, sb])
                main_start = j
        i = j
    if main_start < n:
        pieces.append([main_start, n, m, b])

    # 相邻两段直线延长到交点相接——长方体的角就是两条直线的交点，
    # 中间不留空隙（空隙会露出白底）、也不跟随逐列噪声（保持横平竖直）
    cuts = [float(idx[0])]
    for k in range(len(pieces) - 1):
        s1, e1, m1, b1 = pieces[k]
        s2, e2, m2, b2 = pieces[k + 1]
        cut = (float(idx[e1 - 1]) + float(idx[s2])) / 2.0
        if abs(m1 - m2) > 1e-9:
            xstar = (b2 - b1) / (m1 - m2)
            if idx[s1] - 2 <= xstar <= idx[e2 - 1] + 2:
                cut = xstar
        cut = max(cut, cuts[-1])
        cuts.append(cut)
    cuts.append(float(idx[-1]) + 1)

    out = line.copy()
    for k, (s, e, mm, bb) in enumerate(pieces):
        sel = (idx >= cuts[k]) & (idx < cuts[k + 1])
        out[sel] = mm * idx[sel] + bb

    resid = float(np.median(np.abs(raw - out)))
    return out, resid


def _fit_quad_mask(strict: np.ndarray, loose: np.ndarray, nw: np.ndarray, h: int, w: int):
    """实体书是长方体，正面拍摄的轮廓 = 若干段直线围成的凸多边形（含书脊透视）。
    四个方向各求一条"分段直线"边界：
    上/左/右优先用宽松阈值轮廓（保住书页纸边——实体书的物理边缘、叠压时的
    天然分界线）；底边用严格阈值内收 2px（书底投影必须切，且底边在版式中不可见）。
    宽松线偏离严格线超容差（背景不干净）时该边退回严格轮廓。
    分段拟合后残差仍大（轮廓不像块状实体）返回 None，回退跨度轮廓。"""
    xs = np.where(strict.any(axis=0))[0]
    ys = np.where(strict.any(axis=1))[0]
    if len(xs) < 40 or len(ys) < 40:
        return None
    book_w, book_h = len(xs), len(ys)

    def trim(idx):
        k = max(2, int(len(idx) * 0.04))   # 主线比较时掐掉两端角部
        return idx[k:-k]

    xs_t, ys_t = trim(xs), trim(ys)

    s_top, s_bot, s_left, s_right = _edge_profiles(strict, h, w)
    l_top, _, l_left, l_right = _edge_profiles(loose, h, w)
    xs_l = np.where(loose.any(axis=0))[0]
    ys_l = np.where(loose.any(axis=1))[0]

    def choose(s_prof, l_prof, idx, outward_sign, tol_pick, s_dom, l_dom):
        """宽松轮廓只允许比严格轮廓向外 0~tol_pick（书页边的合理厚度），
        否则退回严格轮廓。outward_sign=+1 向外为更小值(上/左)，-1 为更大值(下/右)。"""
        ms, bs, _ = _robust_line(idx, s_prof[idx])
        ml, bl, _ = _robust_line(idx, l_prof[idx])
        mid = float(idx[len(idx) // 2])
        d = ((ms * mid + bs) - (ml * mid + bl)) * outward_sign
        return (l_prof, l_dom) if -2 <= d <= tol_pick else (s_prof, s_dom)

    top_prof, top_dom = choose(s_top, l_top, xs_t, +1, book_h * 0.08, xs, xs_l)
    left_prof, left_dom = choose(s_left, l_left, ys_t, +1, book_w * 0.06, ys, ys_l)
    right_prof, right_dom = choose(s_right, l_right, ys_t, -1, book_w * 0.06, ys, ys_l)

    tol_v = max(4.0, book_h * 0.012)
    tol_h = max(4.0, book_w * 0.012)
    env_v = book_h * 0.15
    env_h = book_w * 0.15
    gate = max(4.0, min(book_w, book_h) * 0.015)

    top_v, r1 = _seg_boundary(top_dom, top_prof, tol_v, env_v)
    bot_v, r2 = _seg_boundary(xs, s_bot, tol_v, env_v)
    left_v, r3 = _seg_boundary(left_dom, left_prof, tol_h, env_h)
    right_v, r4 = _seg_boundary(right_dom, right_prof, tol_h, env_h)
    if max(r1, r2, r3, r4) > gate:
        return None

    # 白边削除：边界（一条干净折线）整体向内收，把白纸边基本吃掉
    # （实测纸边 2~9px，内收 ~1% 边长；吃进封面 1~3px 缩放后不可见）。
    # 不做任何逐列比较/钳制/两线取大——
    # 两条近平行折线反复交叉会形成锯齿台阶（踩过的坑），边界必须是单一折线
    edge_inset = max(6.0, min(book_w, book_h) * 0.01)
    top_v = top_v + edge_inset
    left_v = left_v + edge_inset
    right_v = right_v - edge_inset

    # 边界数组铺到全幅；有效范围用宽松外延（纸边可能超出严格范围），范围外置空
    x_lo, x_hi = int(xs_l[0]), int(xs_l[-1])
    y_lo, y_hi = int(ys_l[0]), int(ys_l[-1])

    def full_arr(dom, vals, n, lo, hi, empty):
        a = np.full(n, float(empty))
        a[lo:hi + 1] = np.interp(np.arange(lo, hi + 1), dom, vals)
        return a

    top_b = full_arr(top_dom, top_v, w, x_lo, x_hi, h + 1)
    bot_b = full_arr(xs, bot_v - 4, w, x_lo, x_hi, -1)   # 底边内收4px切投影和底部浅色角
    left_b = full_arr(left_dom, left_v, h, y_lo, y_hi, w + 1)
    right_b = full_arr(right_dom, right_v, h, y_lo, y_hi, -1)

    X = np.arange(w)[None, :]
    Y = np.arange(h)[:, None]
    quad = ((Y >= top_b[None, :]) & (Y <= bot_b[None, :]) &
            (X >= left_b[:, None]) & (X <= right_b[:, None]))
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
    每条边 = 拟合直线（横平竖直），仅端部真实缺角（书脊顶斜切等）跟随实际轮廓；
    上/左/右用宽松阈值保书页物理边，底边用严格阈值切投影。
    封面内部的白色区域必然在四边形内部，永远实心不穿帮。
    拟合失败回退严格跨度轮廓。"""
    strict, loose, nw = _masks(img)
    strict = _denoise(strict)
    # loose 不做开运算：纸边只有几像素厚、且内部混有近255的行，开运算会把它整条吃掉；
    # 背景零星噪点交给直线拟合的中位数机制（噪点列被吸附回直线，不会外扩）
    h, w = strict.shape

    quad = _fit_quad_mask(strict, loose, nw, h, w)
    if quad is not None:
        return Image.fromarray((quad.astype(np.uint8)) * 255)

    final = _span_bool(strict, h, w)
    return Image.fromarray((final.astype(np.uint8)) * 255).filter(ImageFilter.MinFilter(3))


def _find_perspective_coeffs(dst_size: tuple, src_quad: list) -> np.ndarray:
    """输出矩形 (W,H) 四角 → 源图四边形四角（TL,TR,BR,BL）的透视系数。"""
    W, H = dst_size
    dst = [(0, 0), (W - 1, 0), (W - 1, H - 1), (0, H - 1)]
    A, B = [], []
    for (X, Y), (x, y) in zip(dst, src_quad):
        A.append([X, Y, 1, 0, 0, 0, -x * X, -x * Y]); B.append(x)
        A.append([0, 0, 0, X, Y, 1, -y * X, -y * Y]); B.append(y)
    return np.linalg.solve(np.array(A, dtype=np.float64), np.array(B, dtype=np.float64))


def rectify_book(img: Image.Image):
    """把书透视矫正成横平竖直的矩形（根本解法）：
    实体书是长方体，照片里就是一个四边形——拟合四条边直线，
    每条边按实测白纸边厚度内收（白边整体切除），四线交点定四角，
    透视变换到正矩形。输出即书本体矩形图：边就是水平线/垂直线，
    物理上不可能出现白边、锯齿、台阶、斜边。拟合失败返回 None 走旧轮廓流程。"""
    strict, loose, nw = _masks(img)
    strict = _denoise(strict)
    h, w = strict.shape

    xs = np.where(strict.any(axis=0))[0]
    ys = np.where(strict.any(axis=1))[0]
    if len(xs) < 40 or len(ys) < 40:
        return None
    book_w, book_h = len(xs), len(ys)

    def trim(idx):
        k = max(2, int(len(idx) * 0.04))
        return idx[k:-k]

    xs_t, ys_t = trim(xs), trim(ys)
    gate = max(5.0, min(book_w, book_h) * 0.02)

    s_top, s_bot, s_left, s_right = _edge_profiles(strict, h, w)
    l_top, l_bot, l_left, l_right = _edge_profiles(loose, h, w)

    # 背景是否干净：宽松内容铺满全图说明背景不是纯白，不能信宽松线
    xs_l = np.where(loose.any(axis=0))[0]
    ys_l = np.where(loose.any(axis=1))[0]
    bg_dirty = len(xs_l) > 0.99 * w and len(ys_l) > 0.99 * h

    def fit(idx, prof):
        m, b, r = _robust_line(idx, prof[idx])
        return (m, b) if r <= gate else None

    def choose(s_prof, l_prof, idx, outward):
        """外沿以宽松线（物理边）为准。白色封面会让严格线深入封面内部、
        残差爆掉——绝不能要求严格线拟合成功，也不能按"离严格线太远"退回
        严格线（会把白封面整个切掉，用户报过"书本体的白色都没了"）。
        仅当背景不干净/宽松线拟合失败/宽松线异常跑到严格线内侧时用严格线。"""
        lf = None if bg_dirty else fit(idx, l_prof)
        sf = fit(idx, s_prof)
        if lf is None:
            return sf, s_prof
        if sf is not None:
            mid = float(idx[len(idx) // 2])
            d = ((sf[0] * mid + sf[1]) - (lf[0] * mid + lf[1])) * outward
            if d < -2:
                return sf, s_prof
        return lf, l_prof

    top, top_prof = choose(s_top, l_top, xs_t, +1)
    left, left_prof = choose(s_left, l_left, ys_t, +1)
    right, right_prof = choose(s_right, l_right, ys_t, -1)
    # 底边优先严格线（排除书底投影）；白封面书严格底线可能拟合失败，
    # 退用宽松底线并加大内收（宽松底线可能落在投影下沿）
    bot = fit(xs_t, s_bot)
    bot_inset = 4.0
    if bot is None and not bg_dirty:
        bot = fit(xs_t, l_bot)
        bot_inset = 12.0
    if not all((top, left, right, bot)):
        return None

    def refine_no_white(line, prof, idx, sign, tol):
        """立体书的边其实是两段直线（书脊段+封面段），单直线在交界处架空会漏白底楔子。
        取最长内点连续段（主段=封面边）重拟合，再把线向内平移到
        几乎处处(p98)不越过实际轮廓——白楔子结构性消除；
        另一段（书脊顶）超出矩形的小角被裁掉，属书脊纯色区无内容损失。
        sign=+1: 上/左边（向内=值增大）；-1: 右边。"""
        vals = prof[idx].astype(np.float64)
        L = line[0] * idx + line[1]
        inlier = np.abs(vals - L) <= tol
        best_s = best_e = 0
        s = None
        for k in range(len(idx) + 1):
            if k < len(idx) and inlier[k]:
                if s is None:
                    s = k
            else:
                if s is not None and k - s > best_e - best_s:
                    best_s, best_e = s, k
                s = None
        m, b = line
        if best_e - best_s >= max(8, len(idx) // 4):
            m, b, _ = _robust_line(idx[best_s:best_e], prof[idx[best_s:best_e]])
        d = (vals - (m * idx + b)) * sign
        shift = float(np.clip(np.percentile(d, 98), 0.0, max(4.0, tol)))
        return (m, b + sign * shift)

    tol_v = max(4.0, book_h * 0.012)
    tol_h = max(4.0, book_w * 0.012)
    top = refine_no_white(top, top_prof, xs_t, +1, tol_v)
    left = refine_no_white(left, left_prof, ys_t, +1, tol_h)
    right = refine_no_white(right, right_prof, ys_t, -1, tol_h)

    # 每条边实测白纸边厚度（近白带中位数，标量），内收 = 厚度 + 3px 保险；
    # 厚度上限防止把封面自身的浅色画面（如浅蓝天空）当白边切掉
    rows_g = np.arange(h)[:, None]
    cols_g = np.arange(w)[None, :]

    def band(line_vals_full, cover_prof, dom, cap):
        d = (cover_prof - line_vals_full)[dom]
        return min(max(float(np.median(d)), 0.0), cap)

    cap_v = max(8.0, book_h * 0.015)
    cap_h = max(8.0, book_w * 0.015)

    lv = top[0] * np.arange(w) + top[1]
    cover = (~(nw | (rows_g < np.ceil(lv)[None, :]))).argmax(axis=0)
    inset_top = 5.0 + band(lv, cover, xs_t, cap_v)

    lv = left[0] * np.arange(h) + left[1]
    cover = (~(nw | (cols_g < np.ceil(lv)[:, None]))).argmax(axis=1)
    inset_left = 5.0 + band(lv, cover, ys_t, cap_h)

    lv = right[0] * np.arange(h) + right[1]
    cover = w - 1 - (~(nw | (cols_g > np.floor(lv)[:, None])))[:, ::-1].argmax(axis=1)
    inset_right = 5.0 + band(-lv, -cover, ys_t, cap_h)

    mt, bt = top[0], top[1] + inset_top
    mb_, bb_ = bot[0], bot[1] - bot_inset    # 底边切投影
    ml, bl = left[0], left[1] + inset_left
    mr, br = right[0], right[1] - inset_right

    # 四线交点 = 四角（上/下边 y=m·x+b；左/右边 x=m·y+b）
    def corner(m_h, b_h, m_v, b_v):
        y = (m_h * b_v + b_h) / (1.0 - m_h * m_v)
        x = m_v * y + b_v
        return (float(np.clip(x, 0, w - 1)), float(np.clip(y, 0, h - 1)))

    TL = corner(mt, bt, ml, bl)
    TR = corner(mt, bt, mr, br)
    BR = corner(mb_, bb_, mr, br)
    BL = corner(mb_, bb_, ml, bl)

    Wd = int(round((np.hypot(TR[0] - TL[0], TR[1] - TL[1]) +
                    np.hypot(BR[0] - BL[0], BR[1] - BL[1])) / 2))
    Hd = int(round((np.hypot(BL[0] - TL[0], BL[1] - TL[1]) +
                    np.hypot(BR[0] - TR[0], BR[1] - TR[1])) / 2))
    if Wd < 30 or Hd < 30:
        return None

    # 立体书的书脊面比封面短（3D透视：书脊顶更低/底更高），按整书一个四边形
    # 量取时书脊上/下方会采到白底 → 白边、"削角"。变换前把书外沿上方/下方的
    # 背景像素用该列书边自身颜色填充，短掉的部分由书脊颜色延伸补齐
    arr = np.array(img)
    t_prof = loose.argmax(axis=0)
    b_prof = h - 1 - loose[::-1, :].argmax(axis=0)
    has = loose.any(axis=0)
    rows_gg = np.arange(h)[:, None]
    cols_i = np.arange(w)
    top_fill = arr[np.clip(t_prof + 3, 0, h - 1), cols_i]
    bot_fill = arr[np.clip(b_prof - 3, 0, h - 1), cols_i]
    m_top = (rows_gg < t_prof[None, :]) & has[None, :]
    m_bot = (rows_gg > b_prof[None, :]) & has[None, :]
    arr = np.where(m_top[:, :, None], top_fill[None, :, :], arr)
    arr = np.where(m_bot[:, :, None], bot_fill[None, :, :], arr)

    coeffs = _find_perspective_coeffs((Wd, Hd), [TL, TR, BR, BL])
    return Image.fromarray(arr.astype(np.uint8)).transform(
        (Wd, Hd), Image.PERSPECTIVE, tuple(coeffs), resample=Image.BICUBIC)


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
        # 主路径：透视矫正成横平竖直的矩形（无白边/锯齿/斜边）
        rect = rectify_book(img)
        if rect is not None:
            books.append((rect, Image.new('L', rect.size, 255)))
            continue
        # 回退：轮廓 mask 流程（拟合失败的非常规图）
        mask = build_book_mask(img)
        am = np.array(mask)
        rows = np.where(am.any(axis=1))[0]
        cols = np.where(am.any(axis=0))[0]
        if len(rows) < 20 or len(cols) < 20:
            raise ValueError("主体裁剪异常")
        box = (int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1)
        books.append((img.crop(box), mask.crop(box)))
    return composite_books(books, n_books, debug=debug)
