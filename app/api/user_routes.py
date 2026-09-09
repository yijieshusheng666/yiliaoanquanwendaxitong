"""用户认证 API：注册 / 登录 / 登出 / 当前用户。

鉴权方式：Authorization: Bearer <token>。
- 未携带有效 token 的用户视为「游客」（user_id=None），
  可访问游客公共空间的历史会话，行为与 P2 之前的版本完全一致；
- 登录用户的所有会话/历史/反馈严格按 user_id 隔离，
  无法读取或删除其他用户的会话。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core import auth as auth_core

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------
class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


# ---------------------------------------------------------------
# 鉴权依赖
# ---------------------------------------------------------------
def get_optional_user(
    authorization: str = Header(default=""),
) -> Optional[dict]:
    """从 Authorization 头解析当前用户；无 token / token 无效返回 None（游客）。"""
    if authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if token:
            return auth_core.get_user_by_token(token)
    return None


def _bearer_token(authorization: str) -> str:
    if authorization.startswith("Bearer "):
        return authorization[7:].strip()
    return ""


# ---------------------------------------------------------------
# 路由
# ---------------------------------------------------------------
@router.post("/register")
async def register(req: RegisterRequest):
    """注册新用户（用户名 3-32 位，密码不少于 6 位），成功即返回 token。"""
    user = auth_core.register(req.username, req.password)
    if user is None:
        return JSONResponse(status_code=400, content={
            "detail": "注册失败：用户名已存在，或不符合规范"
                      "（用户名 3-32 位，密码不少于 6 位）"})
    token = auth_core.create_token(user["id"])
    return {"user": user, "token": token}


@router.post("/login")
async def login(req: LoginRequest):
    """登录，返回 token（有效期默认 7 天，数据库仅存 token 摘要）。"""
    user = auth_core.authenticate(req.username, req.password)
    if user is None:
        return JSONResponse(status_code=401, content={"detail": "用户名或密码错误"})
    token = auth_core.create_token(user["id"])
    return {"user": user, "token": token}


@router.post("/logout")
async def logout(
    user: Optional[dict] = Depends(get_optional_user),
    authorization: str = Header(default=""),
):
    """登出：吊销当前 token（幂等）。"""
    auth_core.revoke_token(_bearer_token(authorization))
    return {"ok": True}


@router.get("/me")
async def me(user: Optional[dict] = Depends(get_optional_user)):
    """返回当前登录用户信息；未登录返回 401。"""
    if user is None:
        return JSONResponse(status_code=401, content={"detail": "未登录"})
    return {"user": user}