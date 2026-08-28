"""Gradio 前端：首页（大图标入口）+ 对话 UI + 引用溯源 + 满意度评价。

通过 HTTP 调用 FastAPI（/api/chat SSE 流式）实现问答；
会话历史由服务端 SQLite 管理（新建/切换/删除）；
满意度反馈通过 /api/feedback 记录，用于后续优化回答质量。
"""
from __future__ import annotations

import json
import os

import gradio as gr
import httpx

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")

# 头像路径（放在 app/ui/static/ 目录，Gradio 可直接 serve 本地文件）
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
BOT_AVATAR = os.path.join(_STATIC_DIR, "bot_avatar.svg")
USER_AVATAR = os.path.join(_STATIC_DIR, "user_avatar.svg")

# ========== 首页机器人 SVG（居中大图标，点击进入聊天） ==========
# 给眼睛/心跳线/天线加 id 以便 CSS 动画驱动
ROBOT_SVG = """
<svg id="med-robot" viewBox="0 0 400 440" xmlns="http://www.w3.org/2000/svg"
     style="width:320px;height:352px;cursor:pointer;filter:drop-shadow(0 12px 28px rgba(56,189,248,.25));">
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
       onclick="var b=document.getElementById('enter-chat-btn');if(b)b.click();">
    {ROBOT_SVG}
    <div id="robot-hint">点击机器人开始咨询</div>
  </div>
  <h1 id="landing-title">💊 医疗安全问答系统</h1>
</div>
"""


def _sources_text(sources) -> str:
    if not sources:
        return ""
    lines = ["", "---", "📄 **引用来源**", ""]
    for i, s in enumerate(sources, 1):
        lines.append(f"{i}. **{s['drug']}** · {s['section']}")
    return "\n".join(lines)


def respond(message: str, history, sid: str = ""):
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


def _fetch_conversations() -> list:
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{API_BASE}/api/conversations")
            resp.raise_for_status()
            return resp.json().get("conversations", [])
    except Exception:
        return []


def _fetch_messages(sid: str) -> list:
    if not sid:
        return []
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{API_BASE}/api/history", params={"session_id": sid})
            resp.raise_for_status()
            return resp.json().get("history", [])
    except Exception:
        return []


def _init_ui():
    """页面加载：拉取会话列表，默认打开最近更新的会话并恢复其消息。
    返回 (会话列表 Radio 的 choices+value 更新, 当前会话ID, 聊天消息, 评价按钮行)。"""
    convs = _fetch_conversations()
    cur = convs[0] if convs else None
    choices = [(_fmt_conv(c), c["id"]) for c in convs]
    value = cur["id"] if cur else None
    msgs = _fetch_messages(cur["id"]) if cur else []
    return (
        gr.update(choices=choices, value=value),
        cur["id"] if cur else "",
        msgs,
        gr.update(visible=False),
    )


def _new_conversation():
    """新建对话并清空聊天区。"""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(f"{API_BASE}/api/conversations")
            resp.raise_for_status()
            new_id = resp.json()["session_id"]
    except Exception:
        new_id = ""
    convs = _fetch_conversations()
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


def _select_conversation(sid: str):
    """切换会话：加载该会话的全部消息，并隐藏评价按钮。"""
    return _fetch_messages(sid), gr.update(visible=False)


def _delete_conversation(cur_sid: str):
    """删除当前会话，随后自动打开列表中最新的会话。"""
    if not cur_sid:
        return (gr.update(choices=[], value=None), "", [], gr.update(visible=False))
    try:
        with httpx.Client(timeout=10) as client:
            client.delete(f"{API_BASE}/api/conversations/{cur_sid}")
    except Exception:
        pass
    convs = _fetch_conversations()
    choices = [(_fmt_conv(c), c["id"]) for c in convs]
    nxt = convs[0] if convs else None
    msgs = _fetch_messages(nxt["id"]) if nxt else []
    return (
        gr.update(choices=choices, value=nxt["id"] if nxt else None),
        nxt["id"] if nxt else "",
        msgs,
        gr.update(visible=False),
    )


def _rate(rating: int, last_qa: dict | None, sid: str):
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
            )
            resp.raise_for_status()
        gr.Info("✅ 已记录反馈，感谢你的评价！"
                if rating == 1 else "✅ 已记录反馈，我们会持续改进！")
    except Exception:
        gr.Warning("⚠️ 反馈服务不可用，请稍后再试")
        return gr.update(visible=True)
    return gr.update(visible=False)


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

_FEEDBACK_CSS = """
/* ========== 首页布局 ========== */
#landing-col {
    min-height: 80vh !important;
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
    font-size: 32px !important;
    font-weight: 800 !important;
    color: #0f172a !important;
    margin: 20px 0 0 0 !important;
    letter-spacing: 0.5px;
    background: linear-gradient(135deg, #0ea5e9, #2563eb);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
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
/* 整体上下浮动 */
#robot-body {
    animation: robotFloat 3.2s ease-in-out infinite;
    transform-origin: center center;
}
@keyframes robotFloat {
    0%, 100% { transform: translateY(0); }
    50%      { transform: translateY(-10px); }
}
/* 光晕呼吸 */
#robot-aura {
    animation: auraPulse 3.2s ease-in-out infinite;
    transform-origin: center center;
}
@keyframes auraPulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50%      { opacity: 0.7; transform: scale(1.08); }
}
/* 地面阴影跟随浮动 */
#robot-shadow {
    animation: shadowPulse 3.2s ease-in-out infinite;
    transform-origin: center center;
}
@keyframes shadowPulse {
    0%, 100% { rx: 100; opacity: 0.35; }
    50%      { rx: 85;  opacity: 0.22; }
}
/* 眨眼 */
.robot-eye {
    animation: eyeBlink 4.5s ease-in-out infinite;
    transform-origin: center;
}
@keyframes eyeBlink {
    0%, 92%, 100% { transform: scaleY(1); }
    95%, 97%      { transform: scaleY(0.08); }
}
/* 天线灯闪烁 */
#robot-antenna-dot {
    animation: antennaBlink 1.8s ease-in-out infinite;
    transform-origin: center;
}
@keyframes antennaBlink {
    0%, 100% { opacity: 1; fill: #34d399; r: 12; }
    50%      { opacity: 0.6; fill: #6ee7b7; r: 14; }
}
/* 心跳线流动 */
#robot-heartbeat {
    animation: heartbeatFlow 2s linear infinite;
}
@keyframes heartbeatFlow {
    0%   { stroke-dashoffset: 0; }
    100% { stroke-dashoffset: -80; }
}

/* 隐藏进入按钮（但保留在DOM中以便JS触发） */
#enter-chat-btn {
    position: absolute !important;
    width: 1px !important;
    height: 1px !important;
    padding: 0 !important;
    margin: 0 !important;
    overflow: hidden !important;
    clip: rect(0,0,0,0) !important;
    white-space: nowrap !important;
    border: 0 !important;
    opacity: 0 !important;
    pointer-events: none !important;
}
"""


def _enter_chat():
    return (
        gr.update(visible=False),
        gr.update(visible=True),
    )


def _back_home():
    """返回首页：保留当前会话展示，不清空聊天记录。"""
    return (
        gr.update(visible=True),
        gr.update(visible=False),
    )


def build_ui() -> gr.Blocks:
    with gr.Blocks(
        title="医疗安全问答系统",
        theme=gr.themes.Soft(),
        css=_FEEDBACK_CSS,
        head=f"<script>{_FEEDBACK_JS}</script>",
    ) as demo:
        # ========== 首页 ==========
        with gr.Column(elem_id="landing-col") as landing_page:
            gr.HTML(LANDING_HTML)
            enter_btn = gr.Button(
                "🩺 点击进入医疗安全咨询",
                size="lg",
                variant="primary",
                elem_id="enter-chat-btn",
            )

        # ========== 聊天页 ==========
        with gr.Column(elem_id="chat-col", visible=False) as chat_page:
            with gr.Row(equal_height=True):
                gr.Markdown(
                    "# 💊 医疗安全问答系统\n"
                    "基于 **RAG + Agent** 的用药安全问答：药物相互作用、特定人群用药、用法用量。\n"
                    "每条回答均**标注引用来源**，遇急症关键词直接提示 **拨打 120**。"
                )
            back_btn = gr.Button("← 返回首页", size="sm", variant="secondary")

            # ===== 主区域：左侧会话列表 + 右侧聊天 =====
            with gr.Row():
                with gr.Column(scale=1, min_width=230):
                    new_btn = gr.Button("➕ 新建对话", variant="primary")
                    conv_list = gr.Radio(
                        label="🗂 历史对话",
                        choices=[],
                        interactive=True,
                        elem_id="conv-list",
                    )
                    del_btn = gr.Button("🗑 删除当前对话", variant="secondary")
                with gr.Column(scale=4):
                    chatbot = gr.Chatbot(
                        type="messages",
                        sanitize_html=False,
                        height=460,
                        avatar_images=(USER_AVATAR, BOT_AVATAR),
                    )
                    with gr.Row(visible=False) as rate_row:
                        like_btn = gr.Button("👍 满意", size="sm")
                        dislike_btn = gr.Button("👎 不满意", size="sm")
                    with gr.Row():
                        msg_box = gr.Textbox(
                            placeholder="输入你的用药问题（例如：布洛芬和阿司匹林能一起吃吗？咳嗽用什么药？）",
                            container=False,
                            scale=8,
                        )
                        send_btn = gr.Button("发送", variant="primary", scale=1)

            cur_sid = gr.State("")
            last_qa = gr.State({})

            # ===== 事件：会话管理 + 问答 + 满意度评价 =====
            demo.load(
                _init_ui,
                inputs=None,
                outputs=[conv_list, cur_sid, chatbot, rate_row],
            )
            new_btn.click(
                _new_conversation,
                inputs=None,
                outputs=[conv_list, cur_sid, chatbot, rate_row],
            )
            conv_list.select(
                _select_conversation,
                inputs=[conv_list],
                outputs=[chatbot, rate_row],
            )
            conv_list.select(
                lambda sid: sid or "",
                inputs=[conv_list],
                outputs=[cur_sid],
            )
            del_btn.click(
                _delete_conversation,
                inputs=[cur_sid],
                outputs=[conv_list, cur_sid, chatbot, rate_row],
            )
            send_btn.click(
                respond,
                inputs=[msg_box, chatbot, cur_sid],
                outputs=[chatbot, msg_box, rate_row, last_qa],
            )
            msg_box.submit(
                respond,
                inputs=[msg_box, chatbot, cur_sid],
                outputs=[chatbot, msg_box, rate_row, last_qa],
            )
            like_btn.click(
                _rate,
                inputs=[gr.State(1), last_qa, cur_sid],
                outputs=[rate_row],
            )
            dislike_btn.click(
                _rate,
                inputs=[gr.State(-1), last_qa, cur_sid],
                outputs=[rate_row],
            )
            gr.Markdown(
                "---\n"
                "*免责声明：系统回答仅供学习参考，不构成医疗建议。用药请遵医嘱，如有不适请及时就医。*\n"
                "*数据来源：《本草纲目》、国家基本药物处方集、国家基本药物临床应用指南。*")
        # 事件绑定：进入聊天 / 返回首页
        enter_btn.click(
            _enter_chat,
            inputs=None,
            outputs=[landing_page, chat_page],
        )
        back_btn.click(
            _back_home,
            inputs=None,
            outputs=[landing_page, chat_page],
        )
    return demo


if __name__ == "__main__":
    build_ui().queue().launch(server_name="0.0.0.0", server_port=7860)
