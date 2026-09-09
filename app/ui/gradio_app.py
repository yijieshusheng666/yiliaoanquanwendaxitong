"""Gradio 前端：首页（大图标入口）+ 独立登录/注册页 + 对话 UI + 引用溯源 + 满意度评价。

页面结构（三个整页切换）：
1. 首页：机器人动画 + 产品简介 + 「开始咨询 / 登录注册」双入口；
2. 认证页：居中卡片，Tab 切换登录 / 注册，支持游客模式跳过；
3. 聊天页：顶部导航栏 + 左侧会话列表 + 右侧聊天区。

通过 HTTP 调用 FastAPI（/api/chat SSE 流式）实现问答；
会话历史由服务端 SQLite 管理（新建/切换/删除）；
满意度反馈通过 /api/feedback 记录，用于后续优化回答质量。
"""
from __future__ import annotations

import json
import os

import gradio as gr
import httpx

from app.config import API_BASE_URL, UI_PORT

API_BASE = os.getenv("API_BASE", API_BASE_URL)

# 头像路径（放在 app/ui/static/ 目录，Gradio 可直接 serve 本地文件）
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
BOT_AVATAR = os.path.join(_STATIC_DIR, "bot_avatar.svg")
USER_AVATAR = os.path.join(_STATIC_DIR, "user_avatar.svg")


def _auth_headers(token: str = "") -> dict:
    """登录态请求头：token 存在时附加 Authorization: Bearer <token>。"""
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}

# ========== 首页机器人 SVG（居中大图标，点击进入聊天） ==========
# 给眼睛/心跳线/天线加 id 以便 CSS 动画驱动
ROBOT_SVG = """
<svg id="med-robot" viewBox="0 0 400 440" xmlns="http://www.w3.org/2000/svg"
     style="width:300px;height:330px;cursor:pointer;filter:drop-shadow(0 12px 28px rgba(56,189,248,.25));">
  <defs>
    <radialGradient id="aura" cx="50%" cy="55%" r="55%">
      <stop offset="0%" stop-color="#7dd3fc" stop-opacity="0.6"/>
      <stop offset="60%" stop-color="#bae6fd" stop-opacity="0.35"/>
      <stop offset="100%" stop-color="#e0f2fe" stop-opacity="0.1"/>
    </radialGradient>
    <linearGradient id="body" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="100%" stop-color="#f0f9ff"/>
    </linearGradient>
  </defs>
  <!-- 外光晕（呼吸） -->
  <ellipse id="robot-aura" cx="200" cy="220" rx="180" ry="195" fill="url(#aura)"/>
  <!-- 地面阴影（跟随浮动缩放） -->
  <ellipse id="robot-shadow" cx="200" cy="408" rx="100" ry="12" fill="#7dd3fc" opacity="0.35"/>
  <!-- 身体（蛋形） -->
  <g id="robot-body">
    <ellipse cx="200" cy="260" rx="120" ry="150" fill="url(#body)" stroke="#cbd5e1" stroke-width="2"/>
    <!-- 头（圆） -->
    <circle cx="200" cy="150" r="105" fill="url(#body)" stroke="#cbd5e1" stroke-width="2"/>
    <!-- 天线杆 -->
    <rect x="196" y="30" width="8" height="45" rx="4" fill="#38bdf8"/>
    <!-- 天线顶圆 -->
    <circle cx="200" cy="30" r="18" fill="#38bdf8"/>
    <circle cx="200" cy="30" r="10" fill="#bae6fd"/>
    <!-- 天线小绿圆（闪烁） -->
    <circle id="robot-antenna-dot" cx="200" cy="78" r="12" fill="#34d399"/>
    <circle cx="200" cy="78" r="6" fill="#a7f3d0"/>
    <!-- 眉毛 -->
    <path d="M115 125 Q155 115 180 125" stroke="#7dd3fc" stroke-width="4" stroke-linecap="round" fill="none"/>
    <path d="M220 125 Q245 115 285 125" stroke="#7dd3fc" stroke-width="4" stroke-linecap="round" fill="none"/>
    <!-- 左眼（眨眼用 scaleY） -->
    <g id="robot-l-eye" class="robot-eye" transform-origin="160 150">
      <ellipse cx="160" cy="150" rx="22" ry="26" fill="#1e293b"/>
      <circle cx="165" cy="145" r="7" fill="#ffffff"/>
      <circle cx="162" cy="152" r="4" fill="#38bdf8"/>
    </g>
    <!-- 右眼 -->
    <g id="robot-r-eye" class="robot-eye" transform-origin="240 150">
      <ellipse cx="240" cy="150" rx="22" ry="26" fill="#1e293b"/>
      <circle cx="245" cy="145" r="7" fill="#ffffff"/>
      <circle cx="242" cy="152" r="4" fill="#38bdf8"/>
    </g>
    <!-- 腮红 -->
    <ellipse cx="125" cy="185" rx="18" ry="12" fill="#fda4af" opacity="0.7"/>
    <ellipse cx="275" cy="185" rx="18" ry="12" fill="#fda4af" opacity="0.7"/>
    <!-- 微笑嘴 -->
    <path d="M170 195 Q200 220 230 195" stroke="#1e293b" stroke-width="5" stroke-linecap="round" fill="none"/>
    <!-- 左手臂 -->
    <path d="M85 270 Q60 300 75 340" stroke="#e2e8f0" stroke-width="26" stroke-linecap="round" fill="none"/>
    <circle cx="75" cy="340" r="22" fill="#e0f2fe" stroke="#cbd5e1" stroke-width="1.5"/>
    <!-- 右手臂 -->
    <path d="M315 270 Q340 300 325 340" stroke="#e2e8f0" stroke-width="26" stroke-linecap="round" fill="none"/>
    <circle cx="325" cy="340" r="22" fill="#e0f2fe" stroke="#cbd5e1" stroke-width="1.5"/>
    <!-- 胸口医疗方块 -->
    <rect x="160" y="290" width="80" height="80" rx="6" fill="#2563eb"/>
    <!-- 白十字 -->
    <rect x="192" y="305" width="16" height="50" fill="#ffffff"/>
    <rect x="175" y="322" width="50" height="16" fill="#ffffff"/>
    <!-- 心跳线（水平偏移动画模拟波形流动） -->
    <polyline id="robot-heartbeat" points="130,330 155,330 165,315 175,345 185,325 195,330 220,330 240,330 255,318 265,342 275,330 300,330"
              stroke="#34d399" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round"
              stroke-dasharray="200" stroke-dashoffset="0"/>
    <!-- 肚子条纹 -->
    <path d="M120 360 Q200 380 280 360" stroke="#bae6fd" stroke-width="4" stroke-linecap="round" fill="none"/>
    <path d="M135 380 Q200 398 265 380" stroke="#bae6fd" stroke-width="3" stroke-linecap="round" fill="none"/>
  </g>
</svg>
"""

LANDING_HTML = f"""
<div id="landing-wrap">
  <div id="robot-click" title="点击机器人开始医疗咨询"
       onclick="var el=document.getElementById('guest-btn');var b=el?(el.tagName==='BUTTON'?el:el.querySelector('button')):null;if(b)b.click();">
    {ROBOT_SVG}
    <div id="robot-hint">点击机器人开始咨询</div>
  </div>
  <h1 id="landing-title">医疗安全问答系统</h1>
  <p id="landing-subtitle">基于 <b>RAG + Agent</b> 的用药安全问答 · 每条回答标注<b>引用来源</b> · 遇急症关键词直接提示 <b>拨打 120</b></p>
  <div id="feature-chips">
    <span class="chip">💊 药物相互作用</span>
    <span class="chip">🤰 特定人群用药</span>
    <span class="chip">📏 用法用量</span>
    <span class="chip">📄 引用溯源</span>
  </div>
</div>
"""

AUTH_HEADER_HTML = """
<div id="auth-header">
  <div id="auth-logo">💊</div>
  <h2 id="auth-title">医疗安全问答系统</h2>
  <p id="auth-subtitle">登录后可保存历史会话，并按账号隔离你的对话空间</p>
</div>
"""


def _sources_text(sources) -> str:
    if not sources:
        return ""
    lines = ["", "---", "📄 **引用来源**", ""]
    for i, s in enumerate(sources, 1):
        lines.append(f"{i}. **{s['drug']}** · {s['section']}")
    return "\n".join(lines)


def respond(message: str, history, sid: str = "", token: str = ""):
    """流式问答。历史由服务端 SQLite 管理（多会话），此处仅渲染。
    消息保持纯文本（引用来源用 Markdown），避免 HTML 混排导致的渲染错位。
    回复完成后在最新回复下方显示满意度评价按钮，评价后隐藏。"""
    history = list(history or []) + [{"role": "user", "content": message}]
    yield history, gr.update(value=""), gr.update(visible=False), gr.update()
    partial, sources = "", []
    try:
        with httpx.Client(timeout=180) as client:
            with client.stream(
                "POST", f"{API_BASE}/api/chat",
                json={"question": message, "session_id": sid, "stream": True},
                headers=_auth_headers(token),
            ) as resp:
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    ev = json.loads(line[len("data: "):])
                    t = ev["type"]
                    if t == "token":
                        partial += ev["content"]
                    elif t == "emergency":
                        partial = ev["content"]
                    elif t == "sources":
                        sources = ev["sources"]
                    elif t == "error":
                        partial += f"\n\n> ⚠️ 生成出错：{ev['message']}"
                    if history and history[-1]["role"] == "assistant":
                        history[-1] = {"role": "assistant", "content": partial}
                    else:
                        history = history + [{"role": "assistant", "content": partial}]
                    yield history, gr.update(), gr.update(visible=False), gr.update()
    except Exception as exc:
        partial += f"\n\n> ⚠️ 服务异常：{exc}"
    if partial:
        if sources:
            partial += "\n\n" + _sources_text(sources)
        if history and history[-1]["role"] == "assistant":
            history[-1] = {"role": "assistant", "content": partial}
        else:
            history = history + [{"role": "assistant", "content": partial}]
    yield (history, gr.update(), gr.update(visible=bool(partial)),
           {"question": message, "answer": partial})


def _fmt_conv(conv: dict) -> str:
    """会话下拉项文案：标题 + 时间。"""
    import datetime
    ts = datetime.datetime.fromtimestamp(conv["updated_at"])
    return f"{conv['title']}（{ts.strftime('%m-%d %H:%M')}）"


def _fetch_conversations(token: str = "") -> list:
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{API_BASE}/api/conversations",
                              headers=_auth_headers(token))
            resp.raise_for_status()
            return resp.json().get("conversations", [])
    except Exception:
        return []


def _fetch_messages(sid: str, token: str = "") -> list:
    if not sid:
        return []
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{API_BASE}/api/history", params={"session_id": sid},
                headers=_auth_headers(token))
            resp.raise_for_status()
            return resp.json().get("history", [])
    except Exception:
        return []


def _new_conversation(token: str = ""):
    """新建对话并清空聊天区。"""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(f"{API_BASE}/api/conversations",
                               headers=_auth_headers(token))
            resp.raise_for_status()
            new_id = resp.json()["session_id"]
    except Exception:
        new_id = ""
    convs = _fetch_conversations(token)
    if new_id:
        # 重新拉列表会让新会话按 updated_at 排到最前（与后端一致）
        cur = next((c for c in convs if c["id"] == new_id), None)
        convs = ([cur] + [c for c in convs if c["id"] != new_id]) if cur else convs
    choices = [(_fmt_conv(c), c["id"]) for c in convs]
    return (
        gr.update(choices=choices, value=new_id if new_id else None),
        new_id,
        [],
        gr.update(visible=False),
    )


def _select_conversation(sid: str, token: str = ""):
    """切换会话：加载该会话的全部消息，并隐藏评价按钮。"""
    return _fetch_messages(sid, token), gr.update(visible=False)


def _delete_conversation(cur_sid: str, token: str = ""):
    """删除当前会话，随后自动打开列表中最新的会话。"""
    if not cur_sid:
        return (gr.update(choices=[], value=None), "", [], gr.update(visible=False))
    try:
        with httpx.Client(timeout=10) as client:
            client.delete(f"{API_BASE}/api/conversations/{cur_sid}",
                          headers=_auth_headers(token))
    except Exception:
        pass
    convs = _fetch_conversations(token)
    choices = [(_fmt_conv(c), c["id"]) for c in convs]
    nxt = convs[0] if convs else None
    msgs = _fetch_messages(nxt["id"], token) if nxt else []
    return (
        gr.update(choices=choices, value=nxt["id"] if nxt else None),
        nxt["id"] if nxt else "",
        msgs,
        gr.update(visible=False),
    )


def _rate(rating: int, last_qa: dict | None, sid: str, token: str = ""):
    """评价最新回复（1 满意 / -1 不满意）。
    评价成功后隐藏按钮行；新回复完成后由 respond 再次显示。"""
    if not last_qa or not last_qa.get("answer"):
        gr.Warning("暂无可评价的回复，请先完成一次问答")
        return gr.update(visible=False)
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"{API_BASE}/api/feedback",
                json={"question": last_qa["question"],
                      "answer": last_qa.get("answer", ""),
                      "rating": rating, "session_id": sid or ""},
                headers=_auth_headers(token),
            )
            resp.raise_for_status()
        gr.Info("✅ 已记录反馈，感谢你的评价！"
                if rating == 1 else "✅ 已记录反馈，我们会持续改进！")
    except Exception:
        gr.Warning("⚠️ 反馈服务不可用，请稍后再试")
        return gr.update(visible=True)
    return gr.update(visible=False)


def _do_auth(username: str, password: str, action: str) -> tuple[str, str]:
    """登录/注册：调用 /api/auth/{action}，成功返回 (token, username)；失败返回 ("", "")。

    注册成功即视为已登录（后端返回 token）。"""
    if not username.strip() or not password:
        gr.Warning("请输入用户名和密码")
        return "", ""
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{API_BASE}/api/auth/{action}",
                json={"username": username.strip(), "password": password})
            if resp.status_code != 200:
                detail = resp.json().get("detail", "操作失败")
                gr.Warning(f"⚠️ {detail}")
                return "", ""
            token = resp.json().get("token", "")
            if token:
                gr.Info("✅ 登录成功！" if action == "login" else "✅ 注册成功，已自动登录！")
            return token, username.strip()
    except Exception as exc:
        gr.Warning(f"⚠️ 认证服务不可用：{exc}")
        return "", ""


def _do_register(username: str, password: str, confirm: str) -> tuple[str, str]:
    """注册：先校验两次密码一致，再走统一认证逻辑。"""
    if password != confirm:
        gr.Warning("⚠️ 两次输入的密码不一致")
        return "", ""
    return _do_auth(username, password, "register")


def _do_logout(token: str):
    """退出登录：调用后端吊销 token（幂等），随后清空本地登录态与表单。"""
    if token:
        try:
            with httpx.Client(timeout=10) as client:
                client.post(f"{API_BASE}/api/auth/logout",
                            headers=_auth_headers(token))
        except Exception:
            pass  # 吊销失败不阻塞登出，token 到期后自然失效
    return ("", "", "", "", "", "")


def _persist_auth(token: str, username: str) -> str:
    """把登录态序列化为 JSON 写入桥接文本框，由前端 JS 同步到 localStorage。"""
    return json.dumps({"t": token or "", "u": username or ""})


def _init_from_persistence(payload: str):
    """页面加载：解析 localStorage 桥接的 JSON，恢复登录态并刷新整个 UI。

    返回 _after_auth 的 9 项输出 + 恢复后的 token + username。"""
    token, username = "", ""
    if payload:
        try:
            d = json.loads(payload or "{}")
            token = d.get("t", "") or ""
            username = d.get("u", "") or ""
        except (ValueError, TypeError):
            pass
    return (*_after_auth(token, username), token, username)


def _after_auth(token: str, username: str):
    """登录/登出后的整页状态刷新：用户徽章、按钮可见性、会话列表切到当前用户空间。

    登录成功后：首页只保留「开始咨询」按钮（去掉游客字样），隐藏「登录/注册」入口；
    退出登录后恢复为游客态的两个按钮。"""
    if token and username:
        user_label = f"👤 {username}"
    else:
        user_label = "🌿 游客模式"
    convs = _fetch_conversations(token)
    choices = [(_fmt_conv(c), c["id"]) for c in convs]
    cur = convs[0] if convs else None
    msgs = _fetch_messages(cur["id"], token) if cur else []
    return (
        user_label,
        gr.update(visible=not token),   # 聊天页「登录/注册」按钮：仅游客可见
        gr.update(visible=bool(token)),  # 聊天页「退出登录」按钮：仅登录可见
        gr.update(choices=choices, value=cur["id"] if cur else None),
        cur["id"] if cur else "",
        msgs,
        gr.update(visible=False),
        # ===== 首页入口按钮跟随登录态 =====
        gr.update(value="🩺 开始咨询" if token else "🩺 开始咨询（游客模式）"),
        gr.update(visible=not token),   # 首页「登录/注册」按钮：仅游客可见
    )


# ========== 页面切换 ==========
def _nav(page: str):
    """三个整页的可见性切换：landing / auth / chat。"""
    return (
        gr.update(visible=page == "landing"),
        gr.update(visible=page == "auth"),
        gr.update(visible=page == "chat"),
    )


def _nav_after_auth(token: str):
    """认证成功后进入聊天页；失败则停留在认证页。"""
    if token:
        return _nav("chat")
    return gr.update(), gr.update(), gr.update()


# 前端 JS：删除会话确认弹窗
_FEEDBACK_JS = """
(function () {
  document.addEventListener("click", function (e) {
    if (!e.target || !e.target.closest) return;
    var btn = e.target.closest("button");
    if (!btn) return;
    var label = (btn.getAttribute("aria-label") || btn.getAttribute("title") || btn.textContent || "").trim();
    if (/删除对话|删除|删除会话/i.test(label)) {
      if (!window.confirm("确定要删除这个对话吗？此操作不可恢复。")) {
        e.stopImmediatePropagation();
        e.preventDefault();
        e.stopPropagation();
      }
    }
  }, true);
})();
"""

_APP_CSS = """
/* ========== 全局 ========== */
.gradio-container {
    max-width: 1280px !important;
    margin: 0 auto !important;
    background: linear-gradient(180deg, #f0f9ff 0%, #f8fafc 30%) !important;
}

/* ========== 首页布局 ========== */
#landing-col {
    min-height: 88vh !important;
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 20px 16px !important;
}
#landing-col > .wrap {
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
}
#landing-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    width: 100%;
    animation: fadeUp .6s ease both;
}
@keyframes fadeUp {
    from { opacity:0; transform:translateY(16px); }
    to   { opacity:1; transform:translateY(0); }
}

/* 标题 */
#landing-title {
    font-size: 34px !important;
    font-weight: 800 !important;
    color: #0f172a !important;
    margin: 14px 0 0 0 !important;
    letter-spacing: 0.5px;
    background: linear-gradient(135deg, #0ea5e9, #2563eb);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

/* 副标题 */
#landing-subtitle {
    margin: 10px 0 0 0;
    font-size: 15px;
    color: #64748b;
    max-width: 640px;
    line-height: 1.7;
}
#landing-subtitle b { color: #2563eb; }

/* 功能标签 */
#feature-chips {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 10px;
    margin-top: 18px;
}
#feature-chips .chip {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 999px;
    padding: 6px 16px;
    font-size: 13px;
    color: #334155;
    box-shadow: 0 2px 8px rgba(15,23,42,.05);
}

/* 首页入口按钮 */
#landing-btns {
    display: flex;
    justify-content: center;
    gap: 16px;
    margin-top: 30px;
    flex-wrap: wrap;
}
#landing-btns button {
    min-width: 200px !important;
    border-radius: 999px !important;
    font-size: 16px !important;
    font-weight: 600 !important;
    padding: 12px 28px !important;
}

/* 提示文字 */
#robot-hint {
    margin-top: 8px;
    font-size: 14px;
    color: #94a3b8;
    opacity: 0;
    animation: hintFade 3s ease-in-out infinite;
    animation-delay: 1s;
}
@keyframes hintFade {
    0%, 100% { opacity: 0; transform: translateY(4px); }
    50%      { opacity: 1; transform: translateY(0); }
}

/* 点击区域 */
#robot-click {
    user-select: none;
    display: flex;
    flex-direction: column;
    align-items: center;
    cursor: pointer;
    border-radius: 24px;
    padding: 8px;
    transition: transform .25s cubic-bezier(.34,1.56,.64,1);
}
#robot-click:hover {
    transform: scale(1.04);
}
#robot-click:active #med-robot {
    transform: scale(0.96) !important;
}

/* ========== 机器人动画 ========== */
#robot-body {
    animation: robotFloat 3.2s ease-in-out infinite;
    transform-origin: center center;
}
@keyframes robotFloat {
    0%, 100% { transform: translateY(0); }
    50%      { transform: translateY(-10px); }
}
#robot-aura {
    animation: auraPulse 3.2s ease-in-out infinite;
    transform-origin: center center;
}
@keyframes auraPulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50%      { opacity: 0.7; transform: scale(1.08); }
}
#robot-shadow {
    animation: shadowPulse 3.2s ease-in-out infinite;
    transform-origin: center center;
}
@keyframes shadowPulse {
    0%, 100% { rx: 100; opacity: 0.35; }
    50%      { rx: 85;  opacity: 0.22; }
}
.robot-eye {
    animation: eyeBlink 4.5s ease-in-out infinite;
    transform-origin: center;
}
@keyframes eyeBlink {
    0%, 92%, 100% { transform: scaleY(1); }
    95%, 97%      { transform: scaleY(0.08); }
}
#robot-antenna-dot {
    animation: antennaBlink 1.8s ease-in-out infinite;
    transform-origin: center;
}
@keyframes antennaBlink {
    0%, 100% { opacity: 1; fill: #34d399; r: 12; }
    50%      { opacity: 0.6; fill: #6ee7b7; r: 14; }
}
#robot-heartbeat {
    animation: heartbeatFlow 2s linear infinite;
}
@keyframes heartbeatFlow {
    0%   { stroke-dashoffset: 0; }
    100% { stroke-dashoffset: -80; }
}

/* ========== 认证页 ========== */
#auth-col {
    min-height: 88vh !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 24px 16px !important;
}
#auth-col > .wrap {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
}
#auth-card {
    width: 100%;
    max-width: 440px;
    background: #ffffff !important;
    border: 1px solid #e2e8f0;
    border-radius: 20px !important;
    box-shadow: 0 16px 48px rgba(15,23,42,.10);
    padding: 32px 36px 28px 36px !important;
    animation: fadeUp .5s ease both;
}
#auth-header { text-align: center; margin-bottom: 20px; }
#auth-logo {
    width: 56px; height: 56px;
    margin: 0 auto 10px auto;
    border-radius: 16px;
    background: linear-gradient(135deg, #e0f2fe, #dbeafe);
    display: flex; align-items: center; justify-content: center;
    font-size: 28px;
    box-shadow: 0 4px 12px rgba(37,99,235,.15);
}
#auth-title {
    margin: 0; font-size: 22px; font-weight: 800; color: #0f172a;
}
#auth-subtitle {
    margin: 6px 0 0 0; font-size: 13px; color: #94a3b8;
}
/* Tab 居中 */
#auth-card .tab-nav {
    justify-content: center !important;
    gap: 8px;
    border-bottom: 1px solid #e2e8f0 !important;
    margin-bottom: 18px;
}
#auth-card .tab-nav button {
    font-size: 15px !important;
    font-weight: 600 !important;
    padding: 8px 28px !important;
}
#auth-card .tab-nav button.selected {
    color: #2563eb !important;
    border-bottom-color: #2563eb !important;
}
/* 认证页按钮 */
#auth-card button.primary, #auth-card button.lg {
    border-radius: 10px !important;
}
.auth-divider {
    display: flex; align-items: center; gap: 12px;
    margin: 18px 0 4px 0; color: #cbd5e1; font-size: 12px;
}
.auth-divider::before, .auth-divider::after {
    content: ""; flex: 1; height: 1px; background: #e2e8f0;
}
.auth-footnote {
    text-align: center; font-size: 12px; color: #94a3b8; margin-top: 14px;
}

/* ========== 聊天页：顶部导航栏 ========== */
#navbar {
    background: #ffffff !important;
    border: 1px solid #e2e8f0;
    border-radius: 16px;
    padding: 10px 18px !important;
    margin: 12px 0 16px 0;
    align-items: center !important;
    box-shadow: 0 4px 16px rgba(15,23,42,.05);
    gap: 12px !important;
}
#brand {
    display: flex; align-items: center; gap: 10px; flex: 1;
    min-width: 0; overflow: hidden;
}
#brand .brand-logo {
    width: 38px; height: 38px; border-radius: 10px;
    background: linear-gradient(135deg, #0ea5e9, #2563eb);
    display: flex; align-items: center; justify-content: center;
    font-size: 20px; color: #fff;
    box-shadow: 0 4px 10px rgba(37,99,235,.25);
}
#brand .brand-name {
    font-size: 18px; font-weight: 800; color: #0f172a; line-height: 1.2;
}
#brand .brand-slogan {
    font-size: 12px; color: #94a3b8; font-weight: 400;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
#brand > div { min-width: 0; }
@media (max-width: 900px) {
    #brand .brand-slogan { display: none; }
}
#user-badge {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    color: #2563eb !important;
    border-radius: 999px;
    padding: 5px 16px;
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
}
#user-badge p { margin: 0 !important; }
#navbar button {
    border-radius: 999px !important;
    white-space: nowrap;
}

/* ========== 聊天页：侧栏 + 主区 ========== */
#sidebar {
    background: #ffffff !important;
    border: 1px solid #e2e8f0;
    border-radius: 16px;
    padding: 16px 14px !important;
    box-shadow: 0 4px 16px rgba(15,23,42,.04);
    gap: 12px !important;
    align-self: flex-start;
}
#sidebar .sidebar-title {
    font-size: 13px; font-weight: 700; color: #64748b;
    letter-spacing: 1px; padding: 0 4px;
}
#new-btn button {
    border-radius: 12px !important;
    font-weight: 600 !important;
}
#conv-list {
    border: none !important;
    background: transparent !important;
    padding: 0 !important;
}
#conv-list label {
    border-radius: 10px !important;
    margin: 2px 0 !important;
    padding: 8px 10px !important;
    font-size: 13px !important;
}
#conv-list label:has(input:checked) {
    background: #eff6ff !important;
    border: 1px solid #bfdbfe !important;
}
#del-btn button {
    border-radius: 12px !important;
}

#chat-main {
    background: #ffffff !important;
    border: 1px solid #e2e8f0;
    border-radius: 16px;
    padding: 16px 18px !important;
    box-shadow: 0 4px 16px rgba(15,23,42,.04);
    gap: 10px !important;
}
/* 隐藏 Chatbot 默认的 "Chatbot" 标签 */
#main-chatbot label {
    display: none !important;
}
/* 输入区 */
#input-row {
    align-items: flex-end !important;
    gap: 10px !important;
}
#input-row textarea {
    border-radius: 12px !important;
}
#send-btn button {
    border-radius: 12px !important;
    font-weight: 600 !important;
    min-height: 44px;
}
/* 评价按钮 */
#rate-row {
    justify-content: flex-end;
    gap: 8px !important;
}
#rate-row button {
    border-radius: 999px !important;
}

/* 免责声明 */
#disclaimer {
    text-align: center;
    font-size: 12px;
    color: #94a3b8;
    margin-top: 14px !important;
    line-height: 1.8;
}

/* 登录态桥接文本框：隐藏但保留在 DOM 中，供前端 JS 读写 localStorage */
#auth-persistence {
    display: none !important;
}
"""


# 前端 JS：把登录态桥接文本框的 JSON 同步到 localStorage（轮询，兼容 Gradio 编程式改值）
_PERSIST_JS = """
(function () {
  var last = null;
  function findInput() {
    var el = document.getElementById('auth-persistence');
    if (!el) return null;
    return el.querySelector('textarea') || el.querySelector('input');
  }
  setInterval(function () {
    var i = findInput();
    if (!i) return;
    var v = i.value;
    if (v === last) return;
    last = v;
    // 空值（初始状态）不处理，避免刷新时误清 localStorage
    if (!v || !v.trim()) return;
    var d;
    try { d = JSON.parse(v); } catch (e) { return; }
    if (typeof d.t === 'undefined') return;
    var t = d.t || '';
    var u = d.u || '';
    if (t) {
      localStorage.setItem('med_token', t);
      localStorage.setItem('med_user', u);
    } else {
      // 显式登出：写入空的 t
      localStorage.removeItem('med_token');
      localStorage.removeItem('med_user');
    }
  }, 300);
})();
"""


def build_ui() -> gr.Blocks:
    with gr.Blocks(
        title="医疗安全问答系统",
        theme=gr.themes.Soft(),
        css=_APP_CSS,
        head=f"<script>{_FEEDBACK_JS}\n{_PERSIST_JS}</script>",
    ) as demo:
        # 登录态桥接文本框：放在所有页面列之外，始终存在于 DOM 中（CSS 隐藏），
        # 前端 JS 轮询其值同步到 localStorage，刷新后由 demo.load 的 js 回调读回。
        auth_persistence = gr.Textbox(
            label="", interactive=False, elem_id="auth-persistence", value="")

        # ========== 首页 ==========
        with gr.Column(elem_id="landing-col") as landing_page:
            gr.HTML(LANDING_HTML)
            with gr.Row(elem_id="landing-btns"):
                guest_btn = gr.Button(
                    "🩺 开始咨询（游客模式）",
                    size="lg", variant="primary", elem_id="guest-btn")
                auth_btn = gr.Button(
                    "🔐 登录 / 注册",
                    size="lg", variant="secondary", elem_id="auth-entry-btn")

        # ========== 登录 / 注册页（独立整页） ==========
        with gr.Column(elem_id="auth-col", visible=False) as auth_page:
            with gr.Column(elem_id="auth-card"):
                gr.HTML(AUTH_HEADER_HTML)
                with gr.Tabs():
                    with gr.Tab("登 录", id="login"):
                        login_user = gr.Textbox(
                            label="用户名", placeholder="请输入用户名（3-32 位）")
                        login_pass = gr.Textbox(
                            label="密码", type="password",
                            placeholder="请输入密码（至少 6 位）")
                        login_btn = gr.Button("登 录", variant="primary", size="lg")
                    with gr.Tab("注 册", id="register"):
                        reg_user = gr.Textbox(
                            label="用户名", placeholder="设置用户名（3-32 位）")
                        reg_pass = gr.Textbox(
                            label="密码", type="password",
                            placeholder="设置密码（至少 6 位）")
                        reg_pass2 = gr.Textbox(
                            label="确认密码", type="password",
                            placeholder="再次输入密码")
                        reg_btn = gr.Button("注册并登录", variant="primary", size="lg")
                gr.HTML('<div class="auth-divider"><span>或</span></div>')
                auth_guest_btn = gr.Button("先逛逛，游客模式进入 →", variant="secondary")
                auth_back_btn = gr.Button("← 返回首页", variant="secondary", size="sm")
                gr.HTML('<div class="auth-footnote">游客模式的会话保存在本地公共空间，登录后按账号隔离</div>')

        # ========== 聊天页 ==========
        with gr.Column(elem_id="chat-col", visible=False) as chat_page:
            # ---- 顶部导航栏 ----
            with gr.Row(elem_id="navbar"):
                gr.HTML(
                    '<div id="brand">'
                    '<div class="brand-logo">💊</div>'
                    '<div><div class="brand-name">医疗安全问答系统</div>'
                    '<div class="brand-slogan">RAG + Agent · 引用溯源 · 急症提示 120</div></div>'
                    '</div>')
                user_status = gr.Markdown("🌿 游客模式", elem_id="user-badge")
                nav_auth_btn = gr.Button(
                    "🔐 登录 / 注册", size="sm", variant="primary")
                logout_btn = gr.Button(
                    "退出登录", size="sm", variant="secondary", visible=False)
                nav_home_btn = gr.Button("🏠 首页", size="sm", variant="secondary")

            # ---- 主区域：左侧会话列表 + 右侧聊天 ----
            with gr.Row():
                with gr.Column(scale=1, min_width=240, elem_id="sidebar"):
                    gr.HTML('<div class="sidebar-title">💬 我的对话</div>')
                    new_btn = gr.Button("➕ 新建对话", variant="primary", elem_id="new-btn")
                    conv_list = gr.Radio(
                        label="历史对话",
                        choices=[],
                        interactive=True,
                        elem_id="conv-list",
                    )
                    del_btn = gr.Button("🗑 删除当前对话", variant="secondary", elem_id="del-btn")
                with gr.Column(scale=4, elem_id="chat-main"):
                    chatbot = gr.Chatbot(
                        type="messages",
                        sanitize_html=False,
                        height=520,
                        avatar_images=(USER_AVATAR, BOT_AVATAR),
                        elem_id="main-chatbot",
                    )
                    with gr.Row(visible=False, elem_id="rate-row") as rate_row:
                        like_btn = gr.Button("👍 满意", size="sm")
                        dislike_btn = gr.Button("👎 不满意", size="sm")
                    with gr.Row(elem_id="input-row"):
                        msg_box = gr.Textbox(
                            placeholder="输入你的用药问题（例如：布洛芬和阿司匹林能一起吃吗？咳嗽用什么药？）",
                            container=False,
                            scale=8,
                        )
                        send_btn = gr.Button("发送", variant="primary", scale=1, elem_id="send-btn")

            gr.Markdown(
                "*免责声明：系统回答仅供学习参考，不构成医疗建议。用药请遵医嘱，如有不适请及时就医。*  \n"
                "*数据来源：《本草纲目》、国家基本药物处方集、国家基本药物临床应用指南。*",
                elem_id="disclaimer")

            cur_sid = gr.State("")
            last_qa = gr.State({})
            token = gr.State("")
            username_state = gr.State("")

            # ===== 事件：会话管理 + 问答 + 满意度评价 =====
            # 页面加载：js 回调从 localStorage 读出上次登录态 → fn 恢复 UI 与 token/username
            demo.load(
                _init_from_persistence,
                inputs=[auth_persistence],
                outputs=[user_status, nav_auth_btn, logout_btn,
                         conv_list, cur_sid, chatbot, rate_row,
                         guest_btn, auth_btn, token, username_state],
                js="""() => {
                    try {
                      var t = localStorage.getItem('med_token') || '';
                      var u = localStorage.getItem('med_user') || '';
                      return [JSON.stringify({t: t, u: u})];
                    } catch (e) { return ['']; }
                }""",
            )
            new_btn.click(
                _new_conversation,
                inputs=[token],
                outputs=[conv_list, cur_sid, chatbot, rate_row],
            )
            conv_list.select(
                _select_conversation,
                inputs=[conv_list, token],
                outputs=[chatbot, rate_row],
            )
            conv_list.select(
                lambda sid: sid or "",
                inputs=[conv_list],
                outputs=[cur_sid],
            )
            del_btn.click(
                _delete_conversation,
                inputs=[cur_sid, token],
                outputs=[conv_list, cur_sid, chatbot, rate_row],
            )
            send_btn.click(
                respond,
                inputs=[msg_box, chatbot, cur_sid, token],
                outputs=[chatbot, msg_box, rate_row, last_qa],
            )
            msg_box.submit(
                respond,
                inputs=[msg_box, chatbot, cur_sid, token],
                outputs=[chatbot, msg_box, rate_row, last_qa],
            )
            like_btn.click(
                _rate,
                inputs=[gr.State(1), last_qa, cur_sid, token],
                outputs=[rate_row],
            )
            dislike_btn.click(
                _rate,
                inputs=[gr.State(-1), last_qa, cur_sid, token],
                outputs=[rate_row],
            )

            # ===== 事件：登录 / 注册（认证页） =====
            _auth_outputs = [user_status, nav_auth_btn, logout_btn,
                             conv_list, cur_sid, chatbot, rate_row,
                             guest_btn, auth_btn]
            login_btn.click(
                _do_auth,
                inputs=[login_user, login_pass, gr.State("login")],
                outputs=[token, username_state],
            ).then(
                _persist_auth, inputs=[token, username_state],
                outputs=[auth_persistence],
            ).then(
                _after_auth, inputs=[token, username_state],
                outputs=_auth_outputs,
            ).then(
                _nav_after_auth, inputs=[token],
                outputs=[landing_page, auth_page, chat_page],
            ).then(
                lambda: "", outputs=[login_pass],
            )
            reg_btn.click(
                _do_register,
                inputs=[reg_user, reg_pass, reg_pass2],
                outputs=[token, username_state],
            ).then(
                _persist_auth, inputs=[token, username_state],
                outputs=[auth_persistence],
            ).then(
                _after_auth, inputs=[token, username_state],
                outputs=_auth_outputs,
            ).then(
                _nav_after_auth, inputs=[token],
                outputs=[landing_page, auth_page, chat_page],
            ).then(
                lambda: ("", ""), outputs=[reg_pass, reg_pass2],
            )
            # 退出登录：先吊销后端 token，再清空本地登录态与表单，回到首页
            logout_btn.click(
                _do_logout,
                inputs=[token],
                outputs=[token, username_state, login_user, login_pass,
                         reg_pass, reg_pass2],
            ).then(
                _persist_auth, inputs=[token, username_state],
                outputs=[auth_persistence],
            ).then(
                _after_auth, inputs=[token, username_state],
                outputs=_auth_outputs,
            ).then(
                lambda: _nav("landing"),
                outputs=[landing_page, auth_page, chat_page],
            )

        # ===== 事件：整页导航 =====
        guest_btn.click(
            lambda: _nav("chat"),
            outputs=[landing_page, auth_page, chat_page])
        auth_btn.click(
            lambda: _nav("auth"),
            outputs=[landing_page, auth_page, chat_page])
        auth_guest_btn.click(
            lambda: _nav("chat"),
            outputs=[landing_page, auth_page, chat_page])
        auth_back_btn.click(
            lambda: _nav("landing"),
            outputs=[landing_page, auth_page, chat_page])
        nav_auth_btn.click(
            lambda: _nav("auth"),
            outputs=[landing_page, auth_page, chat_page])
        nav_home_btn.click(
            lambda: _nav("landing"),
            outputs=[landing_page, auth_page, chat_page])
    return demo


if __name__ == "__main__":
    build_ui().queue().launch(server_name="0.0.0.0", server_port=UI_PORT)
