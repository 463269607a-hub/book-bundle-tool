import io
import pandas as pd


def parse_table(file_bytes: bytes, filename: str) -> list:
    fn_lower = filename.lower()
    if fn_lower.endswith('.csv'):
        for enc in ('utf-8-sig', 'utf-8', 'gbk', 'gb2312', 'gb18030'):
            try:
                df = pd.read_csv(io.BytesIO(file_bytes), encoding=enc, dtype=str)
                break
            except (UnicodeDecodeError, Exception):
                continue
        else:
            raise ValueError("无法识别 CSV 编码，请将文件另存为 UTF-8 格式")
    elif fn_lower.endswith('.xlsx') or fn_lower.endswith('.xls'):
        df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    else:
        raise ValueError(f"不支持的文件格式: {filename}")

    # Normalize column names (strip whitespace)
    df.columns = [str(c).strip() for c in df.columns]

    rows = []
    for _, row in df.iterrows():
        def get_val(col):
            val = row.get(col, None)
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return None
            val = str(val).strip()
            # Remove trailing .0 from numeric strings
            if val.endswith('.0') and val[:-2].isdigit():
                val = val[:-2]
            return val if val else None

        group_id = get_val('group_id')
        output_name = get_val('output_name')
        code_1 = get_val('code_1')
        code_2 = get_val('code_2')
        code_3 = get_val('code_3')
        code_4 = get_val('code_4')
        code_5 = get_val('code_5')

        rows.append({
            'group_id': group_id,
            'output_name': output_name,
            'code_1': code_1,
            'code_2': code_2,
            'code_3': code_3,
            'code_4': code_4,
            'code_5': code_5,
        })

    return rows
