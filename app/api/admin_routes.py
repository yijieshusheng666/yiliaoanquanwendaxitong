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
from app.core.ingestion import SECTION_RE, chunk_document, parse_txt
from app.core.index_versioning import (current_version, index_is_ready,
                                       list_versions, resolve_index_dir, rollback)
from app.api.user_routes import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])

# 仅拦截路径穿越（/ \ ..）与 Windows 非法文件名字符，保留中文/括号等合法药名
_INVALID_RE = re.compile(r'[/\\:*?"<>|]')

# 标准章节白名单：录入非白名单章节仅告警不阻断（区别于镜像/preview 等权威章节）
SECTION_WHITELIST = {
    "成分", "性状", "适应症", "用法用量", "不良反应", "禁忌", "注意事项",
    "特殊人群用药", "孕妇及哺乳期妇女用药", "儿童用药", "老年用药",
    "药物相互作用", "药物过量", "药物相容性", "贮藏", "有效期",
    "人工审核补充",  # 反馈回流产生的章节，需允许避免误报
}
# 必填章节：缺失则禁止保存，保证问答可溯源"治什么 / 怎么吃"
REQUIRED_SECTIONS = ("适应症", "用法用量")
_DDI_BODY_RE = re.compile(r"【药物相互作用】([\s\S]*?)(?=【|$)")
DDI_RISK_RE = re.compile(r"（\s*风险\s*[：:]\s*(高|中|低)\s*）")

DOC_TEMPLATE = (
    "【适应症】用于敏感菌引起的感染，如呼吸道感染、泌尿道感染等。\n"
    "【用法用量】成人一次0.5g，一日3次，饭后服用。\n"
    "【不良反应】常见恶心、腹泻、皮疹；偶见过敏反应。\n"
    "【禁忌】对本品任一成分过敏者禁用。\n"
    "【注意事项】肝肾功能不全者慎用；服用期间避免饮酒。\n"
    "【特殊人群用药】孕妇慎用；哺乳期妇女用药期间暂停哺乳。\n"
    "【药物相互作用】甲硝唑胶囊（风险：中）：合用增强抗菌谱但增加胃肠道反应。；"
    "丙磺舒片（风险：中）：抑制肾小管排泄，延长血药浓度。；"
    "华法林钠片（风险：高）：增强抗凝作用，需监测INR。\n"
    "【贮藏】密封，置阴凉干燥处保存。\n"
)


def validate_doc_content(content: str) -> tuple[list[str], list[str]]:
    """格式校验：返回 (errors, warnings)。errors 非空则禁止保存。"""
    content = content or ""
    errors: list[str] = []
    warnings: list[str] = []
    names = SECTION_RE.findall(content)
    if not names:
        errors.append("未识别到任何【章节】标记，请按标准模板使用 【章节名】内容 格式")
    if content.count("【") != content.count("】"):
        errors.append("【】数量不匹配，存在未闭合的章节标记")
    for req in REQUIRED_SECTIONS:
        if req not in names:
            errors.append(f"缺少必填章节 【{req}】")
    for sname in names:
        if sname not in SECTION_WHITELIST:
            warnings.append(f"章节 【{sname}】 不在标准白名单内，请核实命名")
    m = _DDI_BODY_RE.search(content)
    if m and (body := m.group(1).strip()):
        for entry in re.split(r"[。；]", body):
            entry = entry.strip()
            if entry and not DDI_RISK_RE.search(entry):
                warnings.append(
                    f"药物相互作用条目「{entry[:16]}…」缺少（风险：高/中/低）标注")
    return errors, warnings


def _sanitize_name(name: str) -> str:
    name = (name or "").strip()
    if not name or ".." in name:
        return ""
    name = _INVALID_RE.sub("", name)
    return name if 1 <= len(name) <= 64 else ""


def analyze_doc_completeness(content: str) -> dict:
    """章节完整性分析：找出标准章节中缺失必填/可选章节，供前端提醒"哪里没完善"。"""
    present = [s for s in SECTION_RE.findall(content or "") if s in SECTION_WHITELIST]
    present_set = set(present)
    required_missing = [s for s in REQUIRED_SECTIONS if s not in present_set]
    optional_missing = sorted(
        s for s in SECTION_WHITELIST
        if s not in present_set and s not in REQUIRED_SECTIONS and s != "人工审核补充")
    return {"present": present,
            "missing_required": required_missing,
            "missing_optional": optional_missing,
            "complete": not required_missing}


def _txt_path(name: str) -> Path:
    return TEXT_DIR / f"{name}.txt"


class DocumentUpsert(BaseModel):
    name: str
    content: str


class DocumentOrganize(BaseModel):
    raw_text: str


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
    errors, warnings = validate_doc_content(content)
    if errors:
        return JSONResponse(status_code=400, content={"detail": "；".join(errors)})
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    path = _txt_path(name)
    existed = path.exists()
    path.write_text(content, encoding="utf-8")
    audit_core.record("upsert_document", f"{'更新' if existed else '新增'}文档 {name}",
                      user_id=str(user["id"]), username=user["username"])
    return {"ok": True, "name": name, "existed": existed,
            "warnings": warnings,
            "hint": "索引尚未重建，请前往「索引管理」执行重建"}


@router.get("/documents/template")
async def document_template(user: dict = Depends(require_admin)):
    """标准模板元信息：前端「载入模板」按钮数据源，保证前后端约定单一来源。"""
    return {"template": DOC_TEMPLATE,
            "required": list(REQUIRED_SECTIONS),
            "allowed": sorted(SECTION_WHITELIST),
            "ddi_format": "药品名（风险：高/中/低）：描述，多条用「。；」分隔"}


@router.post("/documents/organize")
async def organize_document(req: DocumentOrganize, user: dict = Depends(require_admin)):
    """AI 智能整理：用 LLM 把说明书原文整理为标准模板文本。只返回整理结果，不落库。"""
    from app.config import ONLINE_MODE
    if not ONLINE_MODE:
        return JSONResponse(status_code=400,
                            content={"detail": "当前为离线模式，需配置 LLM_API_KEY 才可使用 AI 整理"})
    raw = (req.raw_text or "").strip()
    if not raw:
        return JSONResponse(status_code=400, content={"detail": "原文为空，请粘贴说明书文本"})
    from app.core.document_organizer import organize_to_template
    try:
        organized = await run_in_threadpool(organize_to_template, raw)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"detail": f"AI 整理失败：{exc}"})
    return {"organized": organized}


@router.post("/documents/analyze")
async def analyze_document(req: DocumentOrganize, user: dict = Depends(require_admin)):
    """章节完整性分析：返回标准章节中缺失的必填/可选章节，供前端实时提醒。纯规则、不耗 LLM。"""
    return analyze_doc_completeness(req.raw_text or "")


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