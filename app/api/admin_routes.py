"""知识库管理后台 API：文档增删查 + 索引版本治理（仅管理员）。

- 文档以 data/texts/*.txt 为权威输入（文件名=药品名，内容按【章节】结构化）；
- 上传/删除只改语料文件，不自动重建索引——由管理员显式触发 /api/admin/index/rebuild
  （构建耗时且需嵌入模型就绪，避免每次上传都卡顿）；
- 重建走版本化流程（chroma_v{n}），失败自动回滚；重建/回滚后均重置检索单例指向新版本。

鉴权：全部接口 require_admin（Bearer token，role=admin）。
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import TEXT_DIR
from app.core import audit as audit_core
from app.core import review as review_core
from app.core.ingestion import chunk_document, parse_txt
from app.core.index_versioning import (current_version, index_is_ready,
                                       list_versions, resolve_index_dir, rollback)
from app.api.user_routes import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])

# 仅拦截路径穿越（/ \ ..）与 Windows 非法文件名字符，保留中文/括号等合法药名
_INVALID_RE = re.compile(r'[/\\:*?"<>|]')


def _sanitize_name(name: str) -> str:
    name = (name or "").strip()
    if not name or ".." in name:
        return ""
    name = _INVALID_RE.sub("", name)
    return name if 1 <= len(name) <= 64 else ""


def _txt_path(name: str) -> Path:
    return TEXT_DIR / f"{name}.txt"


class DocumentUpsert(BaseModel):
    name: str
    content: str


# ---------------------------------------------------------------
# 文档管理
# ---------------------------------------------------------------
@router.get("/documents")
async def documents(user: dict = Depends(require_admin)):
    items = []
    for p in sorted(TEXT_DIR.glob("*.txt")):
        st = p.stat()
        name = p.stem
        try:
            n_chunks = len(chunk_document(name, parse_txt(p)))
        except Exception:  # noqa: BLE001
            n_chunks = 0
        items.append({"name": name, "size": st.st_size,
                      "chunks": n_chunks, "updated_at": st.st_mtime})
    return {"documents": items, "total": len(items)}


@router.post("/documents")
async def upsert_document(req: DocumentUpsert, user: dict = Depends(require_admin)):
    name = _sanitize_name(req.name)
    if not name:
        return JSONResponse(status_code=400, content={
            "detail": "药品名不合法（1-64 位，仅中英文/数字/下划线/连字符）"})
    content = req.content or ""
    if not content.strip():
        return JSONResponse(status_code=400, content={"detail": "内容不能为空"})
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    path = _txt_path(name)
    existed = path.exists()
    path.write_text(content, encoding="utf-8")
    audit_core.record("upsert_document", f"{'更新' if existed else '新增'}文档 {name}",
                      user_id=str(user["id"]), username=user["username"])
    return {"ok": True, "name": name, "existed": existed,
            "hint": "索引尚未重建，请前往「索引管理」执行重建"}


@router.get("/documents/{name}")
async def document_preview(name: str, user: dict = Depends(require_admin)):
    sname = _sanitize_name(name)
    path = _txt_path(sname)
    if not sname or not path.exists():
        return JSONResponse(status_code=404, content={"detail": "文档不存在"})
    sections = parse_txt(path)
    n_chunks = len(chunk_document(sname, sections))
    return {"name": sname, "chunk_count": n_chunks,
            "sections": [{"section": s, "text": t} for s, t in sections]}


@router.delete("/documents/{name}")
async def delete_document(name: str, user: dict = Depends(require_admin)):
    sname = _sanitize_name(name)
    path = _txt_path(sname)
    if not sname or not path.exists():
        return JSONResponse(status_code=404, content={"detail": "文档不存在"})
    path.unlink()
    audit_core.record("delete_document", f"删除文档 {sname}",
                      user_id=str(user["id"]), username=user["username"])
    return {"ok": True, "name": sname,
            "hint": "索引尚未重建，请前往「索引管理」执行重建"}


# ---------------------------------------------------------------
# 索引版本治理
# ---------------------------------------------------------------
@router.get("/index")
async def index_state(user: dict = Depends(require_admin)):
    return {"ready": index_is_ready(), "current": current_version(),
            "versions": list_versions(), "dir": str(resolve_index_dir())}


@router.post("/index/rebuild")
async def rebuild_index(user: dict = Depends(require_admin)):
    from app.core.retrieval import build_index, reset_knowledge_base
    try:
        n_chunks = await run_in_threadpool(build_index, True)
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"detail": f"重建失败：{exc}"})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"detail": f"重建失败：{exc}"})
    reset_knowledge_base()
    audit_core.record("rebuild_index", f"重建索引，{n_chunks} 个分块",
                      user_id=str(user["id"]), username=user["username"])
    return {"ok": True, "chunk_count": n_chunks}


@router.post("/index/rollback")
async def rollback_index(user: dict = Depends(require_admin)):
    from app.core.retrieval import reset_knowledge_base
    target = rollback()
    if not target:
        return JSONResponse(status_code=400, content={"detail": "无历史版本可回滚"})
    reset_knowledge_base()
    audit_core.record("rollback_index", f"索引回滚到 {target}",
                      user_id=str(user["id"]), username=user["username"])
    return {"ok": True, "current": target}


# ---------------------------------------------------------------
# 反馈闭环：争议问题审核 + 纠错知识回流
# ---------------------------------------------------------------
class ReviewResolve(BaseModel):
    status: str  # resolved | ignored
    note: str = ""
    drug: str = ""      # 回流：目标药品名（可选，仅 resolved 生效）
    content: str = ""   # 回流：纠错补充的知识内容（可选）


def _append_knowledge(drug: str, content: str, reviewed_by: str = "") -> bool:
    """把管理员纠错后的知识以【人工审核补充】章节追加到药品文档，供重建索引后参与检索。"""
    name = _sanitize_name(drug)
    content = (content or "").strip()
    if not name or not content:
        return False
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    path = _txt_path(name)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    block = f"\n【人工审核补充】\n{content}\n"
    path.write_text(text + block, encoding="utf-8")
    audit_core.record("knowledge_reflow", f"纠错知识回流到 {name}", username=reviewed_by)
    return True


@router.get("/reviews")
async def reviews(status: str = "", user: dict = Depends(require_admin)):
    return {"reviews": review_core.list_reviews(status),
            "summary": review_core.summary()}


@router.post("/reviews/{review_id}/resolve")
async def resolve_review(review_id: int, req: ReviewResolve,
                         user: dict = Depends(require_admin)):
    if req.status not in ("resolved", "ignored"):
        return JSONResponse(status_code=400,
                            content={"detail": "status 只能是 resolved 或 ignored"})
    ok = review_core.resolve(review_id, req.status, req.note, user["username"])
    if not ok:
        return JSONResponse(status_code=404, content={"detail": "审核项不存在"})
    reflowed = False
    if req.status == "resolved":
        reflowed = _append_knowledge(req.drug, req.content, user["username"])
    audit_core.record("review", f"审核 {review_id} -> {req.status}",
                      user_id=str(user["id"]), username=user["username"])
    return {"ok": True, "reflowed": reflowed,
            "hint": "已回流知识，请前往「索引管理」重建" if reflowed else ""}