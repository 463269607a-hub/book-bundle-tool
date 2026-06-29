---
title: 图书套装主图批量生成工具
emoji: 📚
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# 图书套装主图批量生成工具

把单本图书白底图按组合表批量合成 800×800 白底套装主图。前端 React + 后端 FastAPI，后端直接托管前端，单服务运行。

## 在线使用

部署后访问平台给出的网址即可，无需登录。

## 本地运行

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --port 8000
# 浏览器打开 http://127.0.0.1:8000
```

Windows 用户可直接双击根目录的 `启动工具.bat`。

## 部署到 Hugging Face Spaces（免费、免信用卡）

1. 注册 https://huggingface.co 账号。
2. 点右上头像 → **New Space**。
3. 填写：
   - **Space name**：`book-bundle-tool`（随意）
   - **License**：选 `mit` 或留空
   - **Select the SDK**：选 **Docker** → **Blank**
   - **Space hardware**：免费的 `CPU basic`
   - 可见性建议 **Public**（同事无需登录即可打开）
4. 创建后把本仓库代码推送到该 Space 的 git 地址（见下）。
5. 等待构建（约 3-5 分钟），完成后得到 `https://用户名-book-bundle-tool.hf.space` 网址，发给同事。

### 推送到 Space

```bash
# 在项目目录，HF_USER 换成你的 HF 用户名
git remote add hf https://huggingface.co/spaces/HF_USER/book-bundle-tool
git push hf main
# git 会要求输入用户名(HF用户名)和密码(HF 的 Access Token，在 设置→Access Tokens 创建 write 权限)
```

## 修改前端后如何更新

```bash
cd frontend
npm install
npm run build      # 重新生成 frontend/dist
cd ..
git add -A && git commit -m "update" && git push hf main
# Space 会自动重新构建部署
```

## 目录结构

```
backend/          FastAPI 后端 + 图像处理
  main.py             接口 + 会话管理 + 托管前端
  image_processor.py  裁白边 + 缩放 + 合成
  templates.py        2/3/4/5 本模板坐标（可调参）
  table_parser.py     CSV/XLSX 解析
frontend/         React 前端
  dist/               打包产物（已提交，供部署使用）
  src/                源码
Dockerfile        Hugging Face Spaces 部署配置
render.yaml       （备用）Render 部署配置
```
