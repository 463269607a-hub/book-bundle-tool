import io
import re

import pandas as pd

# 表头里出现这些关键词才认为文件带表头
_HEADER_KEYS = ('名称', '组套', '子品', 'code', 'output', '编码')
# 子品列表头形如：子品1 / 子品 2 / code_1 / code3 / 编码1
_SUB_PAT = re.compile(r'(?:子品|code_?|编码)\s*(\d+)$', re.IGNORECASE)


def _load_df(file_bytes: bytes, filename: str, header):
    fn = filename.lower()
    if fn.endswith('.csv'):
        for enc in ('utf-8-sig', 'utf-8', 'gbk', 'gb18030'):
            try:
                return pd.read_csv(io.BytesIO(file_bytes), encoding=enc,
                                   dtype=str, header=header)
            except Exception:
                continue
        raise ValueError("无法识别 CSV 编码，请将文件另存为 UTF-8 格式")
    if fn.endswith('.xlsx') or fn.endswith('.xls'):
        return pd.read_excel(io.BytesIO(file_bytes), dtype=str, header=header)
    raise ValueError(f"不支持的文件格式: {filename}")


def parse_table(file_bytes: bytes, filename: str) -> list:
    """宽松解析（用户要求：名称随意写、子品数量随意填、表头可有可无）：
    - 有表头：名称列 = 表头含"名称/组套/output"的列（找不到用第一列）；
      子品列 = 表头形如 子品N/codeN 的列按 N 排序（找不到则名称列以外的所有列按顺序）
    - 无表头（表头行不含任何已知关键词）：第一列 = 组套名称，其余列 = 子品编码
    """
    df = _load_df(file_bytes, filename, header=0)
    cols = [re.sub(r'\s+', '', str(c)) for c in df.columns]

    joined = ''.join(cols).lower()
    if not any(k in joined for k in _HEADER_KEYS):
        # 无表头：重读并按位置命名
        df = _load_df(file_bytes, filename, header=None)
        df.columns = ['组套名称'] + [f'子品{i}' for i in range(1, len(df.columns))]
        cols = list(df.columns)
    else:
        df.columns = cols

    name_col = next(
        (c for c in cols if any(k in c.lower() for k in ('名称', '组套', 'output'))),
        cols[0])

    subs = []
    for c in cols:
        m = _SUB_PAT.fullmatch(c)
        if m:
            subs.append((int(m.group(1)), c))
    sub_cols = [c for _, c in sorted(subs)] or [c for c in cols if c != name_col]

    rows = []
    for _, r in df.iterrows():
        def get_val(col):
            val = r.get(col)
            try:
                if val is None or pd.isna(val):
                    return None
            except (TypeError, ValueError):
                pass
            val = str(val).strip()
            # Excel 数字列会带 .0 后缀
            if val.endswith('.0') and val[:-2].isdigit():
                val = val[:-2]
            return val or None

        codes = [v for v in (get_val(sc) for sc in sub_cols) if v]
        row = {'output_name': get_val(name_col), 'codes': codes}
        # 兼容旧字段（前端/接口展示用）
        for i in range(1, 6):
            row[f'code_{i}'] = codes[i - 1] if i - 1 < len(codes) else None
        rows.append(row)

    # 丢弃完全空行
    return [r for r in rows if r['output_name'] or r['codes']]
