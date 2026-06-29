# 图书套装主图批量生成工具

把单本图书白底图按组合表批量合成 800×800 白底套装主图。前端 React + 后端 FastAPI，后端直接托管前端，单服务运行。

## 在线使用

部署后访问 Render 给出的网址即可，无需登录。

## 本地运行

```bash
# 后端（含已打包前端）
cd backend
pip install -r requirements.txt
uvicorn main:app --port 8000
# 浏览器打开 http://127.0.0.1:8000
```

Windows 用户可直接双击根目录的 `启动工具.bat`。

## 部署到 Render（云端网址）

1. 把本仓库推到 GitHub。
2. 打开 https://render.com ，用 GitHub 账号登录。
3. 点 **New → Blueprint**，选中本仓库，Render 会自动读取 `render.yaml` 配置。
4. 点 **Apply**，等待构建完成（约 2-3 分钟）。
5. 完成后会得到一个 `https://xxx.onrender.com` 网址，发给同事即可使用。

> 说明：Render 免费版在 15 分钟无人访问后会休眠，下次打开需等约 30-50 秒冷启动，属正常现象。

## 修改前端后如何更新

前端改动后需重新打包并提交（Render 用打包好的文件）：

```bash
cd frontend
npm install
npm run build      # 生成 frontend/dist
cd ..
git add -A && git commit -m "update" && git push
# Render 会自动重新部署
```

## 目录结构

```
backend/          FastAPI 后端 + 图像处理
  main.py             接口 + 会话管理 + 托管前端
  image_processor.py  裁白边 + 缩放 + 合成
  templates.py        2/3/4/5 本模板坐标（可调参）
  table_parser.py     CSV/XLSX 解析
frontend/         React 前端
  dist/               打包产物（已提交，供 Render 使用）
  src/                源码
render.yaml       Render 部署配置
```
