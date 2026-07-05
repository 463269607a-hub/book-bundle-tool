import base64
import io
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from image_processor import process_row
from table_parser import parse_table

app = FastAPI(title="图书套装主图批量生成工具")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store
sessions: dict = {}

SESSION_TTL = 6 * 3600  # 超过 6 小时的旧会话在新会话创建时清理


def get_session(session_id: str) -> dict:
    if session_id not in sessions:
        # 404 让前端能识别"会话已过期"（如服务器重启后内存丢失），自动重建会话
        raise HTTPException(status_code=404, detail="会话不存在或已过期，请刷新页面重新上传")
    return sessions[session_id]


def cleanup_old_sessions():
    now = time.time()
    for sid in list(sessions.keys()):
        s = sessions.get(sid)
        if s and now - s.get("created_at", 0) > SESSION_TTL:
            shutil.rmtree(s.get("session_dir", ""), ignore_errors=True)
            sessions.pop(sid, None)


@app.post("/api/session/create")
def create_session():
    cleanup_old_sessions()
    session_id = str(uuid.uuid4())
    session_dir = tempfile.mkdtemp(prefix="bookbundle_")
    sessions[session_id] = {
        "images": {},        # code -> (filename, filepath)
        "table_rows": [],
        "generated": {},     # output_name -> image_bytes
        "session_dir": session_dir,
        "created_at": time.time(),
    }
    return {"session_id": session_id}


@app.post("/api/upload/images")
async def upload_images(
    session_id: str = Form(...),
    files: list[UploadFile] = File(...),
):
    session = get_session(session_id)
    saved = []
    skipped = []
    for f in files:
        fn = f.filename or ""
        if not fn.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            skipped.append({"filename": fn, "reason": "不支持的格式（仅支持 JPG/PNG/WebP）"})
            continue
        # Extract leading digits as code
        m = re.match(r'^(\d+)', os.path.basename(fn))
        if not m:
            skipped.append({"filename": fn, "reason": "文件名不是数字编码开头"})
            continue
        code = m.group(1)
        dest = os.path.join(session["session_dir"], fn)
        content = await f.read()
        with open(dest, 'wb') as fp:
            fp.write(content)
        session["images"][code] = (fn, dest)
        saved.append(fn)

    return {"count": len(session["images"]), "filenames": saved, "skipped": skipped}


@app.post("/api/upload/table")
async def upload_table(
    session_id: str = Form(...),
    file: UploadFile = File(...),
):
    session = get_session(session_id)
    content = await file.read()
    try:
        rows = parse_table(content, file.filename or "file.csv")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"表格解析失败：{e}")
    session["table_rows"] = rows
    return {"count": len(rows), "rows": rows}


def find_matching_code(code: str, images: dict) -> list:
    """Find image keys matching code exactly."""
    pattern = re.compile(r'^' + re.escape(code) + r'(?=\D|$)')
    return [k for k in images.keys() if pattern.match(k)]


def validate_rows(session: dict) -> tuple:
    images = session["images"]
    table_rows = session["table_rows"]

    generatable = []
    failed = []

    for row in table_rows:
        codes = []
        for i in range(1, 6):
            c = row.get(f'code_{i}')
            if c:
                codes.append(c)

        # Check output_name
        if not row.get('output_name'):
            failed.append({"row": row, "reason": "output_name为空"})
            continue

        # Check valid book count
        n = len(codes)
        if n < 2 or n > 5:
            failed.append({"row": row, "reason": f"书本数量无效：{n}（需2-5本）"})
            continue

        # Check duplicate codes within row
        if len(set(codes)) != len(codes):
            failed.append({"row": row, "reason": "同行重复编码"})
            continue

        # Check each code matches exactly one image
        row_failed = False
        for code in codes:
            matches = find_matching_code(code, images)
            if len(matches) == 0:
                failed.append({"row": row, "reason": f"编码未匹配：{code}"})
                row_failed = True
                break
            elif len(matches) > 1:
                failed.append({"row": row, "reason": f"编码不唯一：{code}"})
                row_failed = True
                break

        if not row_failed:
            generatable.append(row)

    return generatable, failed


@app.post("/api/validate")
def validate(body: dict):
    session_id = body.get("session_id")
    session = get_session(session_id)
    generatable, failed = validate_rows(session)
    return {"generatable": generatable, "failed": failed}


@app.post("/api/generate")
def generate(body: dict):
    """启动后台生成线程并立即返回，前端轮询 /api/generate/status 拿真实进度。"""
    session_id = body.get("session_id")
    debug = body.get("debug", False)
    session = get_session(session_id)
    images = session["images"]

    prev = session.get("gen_state")
    if prev and prev.get("running"):
        raise HTTPException(status_code=409, detail="正在生成中，请稍候")

    generatable, pre_failed = validate_rows(session)
    state = {
        "running": True,
        "current": 0,
        "total": len(generatable),
        "results": [],
        "failed": list(pre_failed),
    }
    session["gen_state"] = state
    # 每次重新生成清空上一轮结果，避免 ZIP 里混入旧文件
    session["generated"] = {}

    def worker():
        # Track output name duplicates
        name_counts: dict = {}

        def unique_name(name: str) -> str:
            if name not in name_counts:
                name_counts[name] = 1
                return name
            else:
                name_counts[name] += 1
                return f"{name}_{name_counts[name]}"

        try:
            for row in generatable:
                codes = []
                for i in range(1, 6):
                    c = row.get(f'code_{i}')
                    if c:
                        codes.append(c)
                n = len(codes)
                output_name = unique_name(row['output_name'])

                try:
                    book_imgs = []
                    for code in codes:
                        matches = find_matching_code(code, images)
                        _, fpath = images[matches[0]]
                        img = Image.open(fpath)
                        img.load()
                        book_imgs.append(img)

                    result_img = process_row(book_imgs, n, debug=debug)

                    buf = io.BytesIO()
                    result_img.save(buf, format='JPEG', quality=95)
                    img_bytes = buf.getvalue()

                    session["generated"][output_name] = img_bytes

                    img_b64 = base64.b64encode(img_bytes).decode('utf-8')
                    state["results"].append({"output_name": output_name, "image_b64": img_b64})

                except Exception as e:
                    state["failed"].append({"row": row, "reason": str(e)})

                state["current"] += 1
        finally:
            state["running"] = False

    threading.Thread(target=worker, daemon=True).start()
    return {"started": True, "total": state["total"]}


@app.get("/api/generate/status/{session_id}")
def generate_status(session_id: str):
    session = get_session(session_id)
    state = session.get("gen_state")
    if not state:
        return {"running": False, "current": 0, "total": 0, "results": [], "failed": []}
    resp = {"running": state["running"], "current": state["current"], "total": state["total"]}
    if not state["running"]:
        resp["results"] = state["results"]
        resp["failed"] = state["failed"]
    return resp


@app.get("/api/download/image/{session_id}/{output_name}")
def download_image(session_id: str, output_name: str):
    session = get_session(session_id)
    img_bytes = session["generated"].get(output_name)
    if not img_bytes:
        return Response(status_code=404)
    from urllib.parse import quote
    encoded_name = quote(f"{output_name}.jpg")
    return Response(
        content=img_bytes,
        media_type="image/jpeg",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


@app.post("/api/download/zip")
def download_zip(body: dict):
    session_id = body.get("session_id")
    session = get_session(session_id)
    generated = session["generated"]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, img_bytes in generated.items():
            zf.writestr(f"{name}.jpg", img_bytes)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''book_bundles.zip"},
    )


# Serve frontend static files (must be after all API routes)
_frontend_dist = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')
if os.path.isdir(_frontend_dist):
    from fastapi.responses import FileResponse

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        file_path = os.path.join(_frontend_dist, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(_frontend_dist, 'index.html'))
