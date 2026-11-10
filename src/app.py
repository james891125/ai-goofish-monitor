"""Shopee Taiwan application. Legacy Xianyu routes and processes are not mounted."""
import hmac
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from src.api.routes import prompts, shopee
from src.infrastructure.persistence.shopee_repository import ShopeeRepository
from src.services.shopee_runtime import ShopeeRuntime

load_dotenv(dotenv_path='.env',override=True,interpolate=False)
SESSIONS: dict[str,float]={}
LOGIN_ATTEMPTS: dict[str,list[float]]={}
SESSION_TTL=8*60*60


def credentials():
    user,password=os.getenv('WEB_USERNAME','').strip(),os.getenv('WEB_PASSWORD','')
    if not user or len(password.strip())<12 or password.lower() in {'admin123','change-me','change-me-now','changeme12345'}:
        raise ValueError('請在 .env 設定 WEB_USERNAME 與至少 12 字元的非預設 WEB_PASSWORD。')
    return user,password


def authenticated(request):
    token=request.cookies.get('shopee_session','')
    if SESSIONS.get(token,0)>time.monotonic(): return True
    return False


@asynccontextmanager
async def lifespan(app):
    credentials()
    app.state.runtime=ShopeeRuntime(ShopeeRepository())
    app.state.runtime.start()
    yield
    await app.state.runtime.close()
    SESSIONS.clear()


app=FastAPI(title='臺灣蝦皮 AI 二手商品監控',version='3.0.0-preview',lifespan=lifespan,
            docs_url=None,redoc_url=None,openapi_url=None)


@app.middleware('http')
async def secure_api(request,call_next):
    # Cookie sessions are same-origin, httpOnly, and never contain account credentials.
    if request.method not in {'GET','HEAD','OPTIONS'}:
        origin=request.headers.get('origin')
        if origin and urlparse(origin).netloc != request.headers.get('host'):
            return JSONResponse({'detail':'不允許跨來源修改。'},status_code=403)
        length=request.headers.get('content-length')
        if length and (not length.isdigit() or int(length)>5_000_000):
            return JSONResponse({'detail':'請求大小超過 5 MB。'},status_code=413)
    if request.url.path.startswith('/api/') and not authenticated(request):
        return JSONResponse({'detail':'請先登入。'},status_code=401)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Frame-Options']='DENY'
    if request.url.path.startswith(('/api/','/auth/')):
        response.headers['Cache-Control']='no-store'
    return response


app.include_router(shopee.router)
app.include_router(prompts.router)


class LoginRequest(BaseModel):
    username: str=Field(max_length=200)
    password: str=Field(max_length=1000)


@app.post('/auth/status')
async def login(payload: LoginRequest,request: Request):
    key=request.client.host if request.client else 'unknown'
    now=time.monotonic()
    attempts=[at for at in LOGIN_ATTEMPTS.get(key,[]) if at>now-60]
    LOGIN_ATTEMPTS[key]=attempts
    if len(attempts)>=10: raise HTTPException(429,'登入嘗試過多，請一分鐘後再試。')
    expected_user,expected_password=credentials()
    if not (hmac.compare_digest(payload.username.encode(),expected_user.encode()) and hmac.compare_digest(payload.password.encode(),expected_password.encode())):
        attempts.append(now)
        raise HTTPException(401,'帳號或密碼錯誤。')
    LOGIN_ATTEMPTS.pop(key,None)
    for token,expires in list(SESSIONS.items()):
        if expires<=now: SESSIONS.pop(token,None)
    if len(SESSIONS)>1000: SESSIONS.clear()
    token=secrets.token_urlsafe(32)
    SESSIONS[token]=now+SESSION_TTL
    response=JSONResponse({'authenticated':True,'username':payload.username})
    response.set_cookie('shopee_session',token,httponly=True,samesite='strict',
                        secure=request.url.scheme=='https',max_age=SESSION_TTL)
    return response


@app.get('/auth/status')
async def auth_status(request: Request):
    if not authenticated(request): raise HTTPException(401,'請先登入。')
    return {'authenticated':True}


@app.post('/auth/logout')
async def logout(request: Request):
    SESSIONS.pop(request.cookies.get('shopee_session',''),None)
    response=JSONResponse({'logged_out':True}); response.delete_cookie('shopee_session')
    return response


@app.get('/health')
async def health():
    return {'status':'healthy','release_status':'waiting_authorization','application':'shopee_tw_monitor'}


if Path('dist/assets').is_dir(): app.mount('/assets',StaticFiles(directory='dist/assets'),name='assets')


@app.get('/{path:path}')
async def frontend(path: str):
    if path.startswith(('api/','auth/')): raise HTTPException(404,'找不到此功能。')
    if Path('dist/index.html').is_file(): return FileResponse('dist/index.html')
    return JSONResponse({'detail':'請先建置前端：cd web-ui && npm ci && npm run build'},status_code=503)


if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host=os.getenv('HOST','127.0.0.1'),port=int(os.getenv('SERVER_PORT','8000')))
