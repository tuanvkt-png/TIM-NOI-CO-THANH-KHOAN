# HƯỚNG DẪN DEPLOY LÊN GITHUB + RENDER (bản v2 — đã fix lỗi)

## Cấu trúc file cần upload
```
app/__init__.py
app/main.py
app/data_fetcher.py
app/analyzer.py
app/scheduler.py
app/db.py
templates/index.html
static/css/style.css
static/js/app.js
static/js/lightweight-charts.standalone.production.js   ← QUAN TRỌNG: thư viện chart nhúng sẵn
requirements.txt
Procfile
render.yaml
.gitignore
```

## GitHub
1. github.com → + → New repository → tên `trading-web-signature` → Public → Create
2. Add file → Upload files → kéo TẤT CẢ file/thư mục ở trên → Commit changes

## Render
1. render.com → New + → Web Service → chọn repo vừa tạo
2. Runtime: Python 3
3. Build Command: pip install -r requirements.txt
4. Start Command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
5. Instance type: Free → Create Web Service
6. Chờ 3–5 phút → lấy link dạng https://trading-web-signature.onrender.com

## Không cần Environment Variables
