import asyncio
import json
import os
import sqlite3
import time
import aiosqlite
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

# ── Config ──────────────────────────────────────
DB_PATH = "webhooks.db"
BR_TZ   = ZoneInfo("America/Sao_Paulo")
PORT    = int(os.environ.get("PORT", 8000))

# ── DB ──────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS webhooks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            lote         TEXT,
            timestamp    TEXT,
            ip           TEXT,
            cidade       TEXT,
            regiao       TEXT,
            pais         TEXT,
            tamanho_kb   REAL,
            tempo_ms     REAL,
            method       TEXT,
            query_params TEXT,
            payload      TEXT,
            headers      TEXT
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_id ON webhooks(id DESC)")
    con.commit()
    con.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

# ── Helpers ─────────────────────────────────────
def get_real_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "desconhecido"

async def get_geo(ip: str) -> dict:
    """Consulta localização do IP via ip-api.com (gratuito, sem chave)"""
    try:
        if ip in ("127.0.0.1", "::1", "desconhecido"):
            return {"cidade": "Local", "regiao": "—", "pais": "—"}
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"http://ip-api.com/json/{ip}?fields=city,regionName,country,status")
            data = r.json()
            if data.get("status") == "success":
                return {
                    "cidade": data.get("city", "—"),
                    "regiao": data.get("regionName", "—"),
                    "pais":   data.get("country", "—"),
                }
    except Exception:
        pass
    return {"cidade": "—", "regiao": "—", "pais": "—"}

async def save_webhook(lote, ip, geo, tamanho_kb, tempo_ms, method, query_params, payload, headers):
    ts = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO webhooks
              (lote, timestamp, ip, cidade, regiao, pais, tamanho_kb, tempo_ms, method, query_params, payload, headers)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            lote, ts, ip,
            geo["cidade"], geo["regiao"], geo["pais"],
            round(tamanho_kb, 2), round(tempo_ms, 1),
            method, query_params, payload, headers
        ))
        await db.commit()

# ── ENDPOINT: receber webhook ────────────────────
@app.post("/webhook")
@app.get("/webhook")
@app.put("/webhook")
@app.patch("/webhook")
async def receive_webhook(request: Request, lote: str = Query(default=None)):
    t_inicio = time.monotonic()

    ip = get_real_ip(request)

    lote_final = (
        lote
        or request.headers.get("x-lote")
        or request.headers.get("x-batch")
        or "sem-identificador"
    )

    try:
        body_bytes = await request.body()
        tamanho_kb = len(body_bytes) / 1024
        payload_str = body_bytes.decode("utf-8", errors="replace")
        try:
            payload_str = json.dumps(json.loads(payload_str), ensure_ascii=False, indent=2)
        except Exception:
            pass
    except Exception:
        body_bytes = b""
        tamanho_kb = 0
        payload_str = ""

    tempo_ms = (time.monotonic() - t_inicio) * 1000

    # Query params (exceto 'lote' que já capturamos)
    qp = dict(request.query_params)
    query_params_str = json.dumps(qp, ensure_ascii=False) if qp else "{}"

    headers_dict = {k: v for k, v in request.headers.items()}
    headers_str  = json.dumps(headers_dict, ensure_ascii=False)

    method = request.method

    # Fire-and-forget: geo + save
    async def enrich_and_save():
        geo = await get_geo(ip)
        await save_webhook(
            lote_final, ip, geo, tamanho_kb, tempo_ms,
            method, query_params_str, payload_str, headers_str
        )

    asyncio.create_task(enrich_and_save())

    return JSONResponse({"status": "ok", "recebido": True}, status_code=200)

# ── ENDPOINT: dashboard ──────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    page: int  = Query(default=1, ge=1),
    lote: str  = Query(default=""),
    per_page: int = Query(default=50)
):
    per_page = max(10, min(per_page, 500))
    offset   = (page - 1) * per_page

    where  = "WHERE lote LIKE ?" if lote else ""
    params = (f"%{lote}%",) if lote else ()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(f"SELECT COUNT(*) as cnt FROM webhooks {where}", params) as cur:
            total = (await cur.fetchone())["cnt"]

        async with db.execute(f"""
            SELECT id, lote, timestamp, ip, cidade, pais, tamanho_kb, tempo_ms, method, query_params, payload
            FROM webhooks {where}
            ORDER BY id DESC LIMIT ? OFFSET ?
        """, (*params, per_page, offset)) as cur:
            rows = await cur.fetchall()

        async with db.execute("SELECT DISTINCT lote FROM webhooks ORDER BY lote") as cur:
            lotes = [r["lote"] for r in await cur.fetchall()]

    total_pages = max(1, (total + per_page - 1) // per_page)

    records = []
    for r in rows:
        payload_preview = (r["payload"] or "")[:80]
        records.append({
            "id":       r["id"],
            "lote":     r["lote"],
            "timestamp":r["timestamp"],
            "ip":       r["ip"],
            "cidade":   r["cidade"] or "—",
            "pais":     r["pais"] or "—",
            "tamanho":  f"{r['tamanho_kb']:.1f} KB" if r["tamanho_kb"] else "—",
            "tempo":    f"{r['tempo_ms']:.0f} ms" if r["tempo_ms"] else "—",
            "method":   r["method"] or "POST",
            "query_params": r["query_params"] or "{}",
            "payload":  r["payload"] or "",
            "preview":  payload_preview,
        })

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "records": records,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "lote_filter": lote,
        "lotes": lotes,
    })

# ── ENDPOINT: detalhe ────────────────────────────
@app.get("/webhook/{wid}")
async def get_detail(wid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM webhooks WHERE id=?", (wid,)) as cur:
            row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Não encontrado")
    return dict(row)

# ── ENDPOINT: limpar ─────────────────────────────
@app.delete("/webhooks")
async def clear_all():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM webhooks")
        await db.commit()
        await db.execute("VACUUM")
        await db.commit()
    return {"status": "limpo"}

# ── ENDPOINT: stats ──────────────────────────────
@app.get("/stats")
async def stats():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT COUNT(*) as cnt FROM webhooks") as cur:
            total = (await cur.fetchone())["cnt"]
        async with db.execute("SELECT timestamp FROM webhooks ORDER BY id DESC LIMIT 1") as cur:
            last = await cur.fetchone()
    return {"total": total, "ultimo": last["timestamp"] if last else None}
