"""用户认证 API：注册 / 登录 / 登出 / 当前用户 / 管理员审计与用户列表。

鉴权方式：Authorization: Bearer <token>。
- 未携带有效 token 的用户视为「游客」（user_id=None），
  可访问游客公共空间的历史会话，行为与之前版本完全一致；
- 登录用户的所有会话/历史/反馈严格按 user_id 隔离；
- admin 角色可访问 /api/auth/users 与 /api/auth/audit。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core import auth as auth_core
from app.core import audit as audit_core
from app.core.auth import ROLE_ADMIN

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


def require_admin(user: Optional[dict] = Depends(get_optional_user)) -> dict:
    """管理员专用依赖：非 admin 抛出 403。"""
    if user is None or user.get("role") != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


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
    audit_core.record("register", f"用户 {user['username']} 注册（角色 {user['role']}）",
                      user_id=str(user["id"]), username=user["username"])
    return {"user": user, "token": token}


@router.post("/login")
async def login(req: LoginRequest):
    """登录，返回 token（有效期默认 7 天，数据库仅存 token 摘要）。"""
    user = auth_core.authenticate(req.username, req.password)
    if user is None:
        audit_core.record("login_failed", f"用户名 {req.username}", username=req.username)
        return JSONResponse(status_code=401, content={"detail": "用户名或密码错误"})
    token = auth_core.create_token(user["id"])
    audit_core.record("login", f"用户 {user['username']} 登录",
                      user_id=str(user["id"]), username=user["username"])
    return {"user": user, "token": token}


@router.post("/logout")
async def logout(
    user: Optional[dict] = Depends(get_optional_user),
    authorization: str = Header(default=""),
):
    """登出：吊销当前 token（幂等）。"""
    auth_core.revoke_token(_bearer_token(authorization))
    if user:
        audit_core.record("logout", f"用户 {user['username']} 登出",
                          user_id=str(user["id"]), username=user["username"])
    return {"ok": True}


@router.get("/me")
async def me(user: Optional[dict] = Depends(get_optional_user)):
    """返回当前登录用户信息；未登录返回 401。"""
    if user is None:
        return JSONResponse(status_code=401, content={"detail": "未登录"})
    return {"user": user}


@router.get("/users")
async def users(user: dict = Depends(require_admin)):
    """管理员：列出全部注册用户。"""
    return {"users": auth_core.list_users()}


@router.get("/audit")
async def audit(limit: int = 100, user: dict = Depends(require_admin)):
    """管理员：查看最近操作审计日志。"""
    return {"logs": audit_core.list_logs(limit)}