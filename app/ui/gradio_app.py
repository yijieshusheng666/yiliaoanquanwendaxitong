"""Gradio 前端：首页（大图标入口）+ 对话 UI + 引用溯源 + 反馈按钮。

通过 HTTP 调用 FastAPI（/api/chat SSE 流式）实现问答；
点赞/点踩通过 /api/feedback 记录到本地 JSON 文件。
"""
from __future__ import annotations

import html
import json
import os

import gradio as gr
import httpx

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")

# 头像路径（放在项目根目录，Gradio 可直接 serve 本地文件）
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BOT_AVATAR = os.path.join(_PROJECT_ROOT, "bot_avatar.svg")
USER_AVATAR = os.path.join(_PROJECT_ROOT, "user_avatar.svg")

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


def _feedback_html(question: str) -> str:
    q = html.escape(question or "", quote=True)
    return (
        f'<div class="qa-fb" data-q="{q}">'
        f'<button type="button" class="qfb" data-v="1" title="有帮助">👍</button>'
        f'<button type="button" class="qfb" data-v="-1" title="没帮助">👎</button>'
        f"</div>"
    )


def _sources_text(sources) -> str:
    if not sources:
        return ""
    lines = ["", "---", "📄 **引用来源**", ""]
    for i, s in enumerate(sources, 1):
        lines.append(f"{i}. **{s['drug']}** · {s['section']}")
    return "\n".join(lines)


def respond(message: str, history):
    hist_req = [{"role": h["role"], "content": h["content"]}
                for h in history[-6:]]
    partial, sources = "", []
    with httpx.Client(timeout=180) as client:
        with client.stream(
            "POST", f"{API_BASE}/api/chat",
            json={"question": message, "history": hist_req, "stream": True},
        ) as resp:
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                ev = json.loads(line[len("data: "):])
                t = ev["type"]
                if t == "token":
                    partial += ev["content"]
                    yield partial
                elif t == "emergency":
                    partial = ev["content"]
                    yield partial
                elif t == "sources":
                    sources = ev["sources"]
                elif t == "error":
                    partial += f"\n\n> ⚠️ 生成出错：{ev['message']}"
                    yield partial
                elif t == "done":
                    partial += _sources_text(sources)
                    yield partial
    if partial:
        yield partial + _feedback_html(message)


# 前端 JS：反馈提交 + 首页点击机器人进入聊天 + 清空确认

_FEEDBACK_JS = f"""
window.__API_BASE__ = "{API_BASE}";
(function () {{
  function toast(msg) {{
    var t = document.createElement("div");
    t.textContent = msg;
    t.style.cssText = "position:fixed;left:50%;bottom:24px;transform:translateX(-50%);" +
      "background:rgba(17,24,39,.92);color:#fff;padding:8px 18px;border-radius:8px;" +
      "z-index:99999;font-size:14px;box-shadow:0 2px 8px rgba(0,0,0,.2);";
    document.body.appendChild(t);
    setTimeout(function () {{ t.remove(); }}, 2500);
  }}
  function record(q, a, rating) {{
    try {{
      fetch(window.__API_BASE__ + "/api/feedback", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ question: q, answer: a, rating: rating, session_id: "web-ui" }})
      }}).then(function (r) {{ return r.json(); }})
        .then(function () {{ toast("✅ 已记录你的反馈，感谢支持！"); }})
        .catch(function () {{ toast("⚠️ 反馈服务不可用"); }});
    }} catch (e) {{ toast("⚠️ 反馈提交失败"); }}
  }}
  document.addEventListener("click", function (e) {{
    var b = e.target && e.target.closest && e.target.closest(".qfb");
    if (!b) return;
    e.preventDefault();
    var wrap = b.closest(".qa-fb");
    var row = wrap ? wrap.parentElement : null;
    var question = wrap ? (wrap.getAttribute("data-q") || "") : "";
    var answer = row ? row.textContent.replace(/[👍👎已记录]/g, "").trim() : "";
    var rating = b.getAttribute("data-v") === "1" ? 1 : -1;
    record(question, answer, rating);
  }});
  // 删除/清空聊天记录前弹窗确认
  document.addEventListener("click", function (e) {{
    if (!e.target || !e.target.closest) return;
    var btn = e.target.closest("button");
    if (!btn) return;
    var label = (btn.getAttribute("aria-label") || btn.getAttribute("title") || btn.textContent || "").trim();
    if (/清空对话|清空|删除|clear|delete/i.test(label)) {{
      if (!window.confirm("确定要删除聊天记录吗？此操作不可恢复。")) {{
        e.stopImmediatePropagation();
        e.preventDefault();
        e.stopPropagation();
      }}
    }}
  }}, true);
}})();
"""

_FEEDBACK_CSS = """
.qa-fb { display:flex; flex-direction:row; gap:6px; margin-top:10px; opacity:1; visibility:visible; }
.qa-fb .qfb {
    border:1px solid var(--border-color-primary,#d0d7de);
    background:var(--button-secondary-background-fill,#fff);
    border-radius:999px; font-size:14px; line-height:1; padding:4px 10px; cursor:pointer;
    transition:transform .12s ease, box-shadow .12s ease;
}
.qa-fb .qfb:hover { transform:translateY(-1px); box-shadow:0 1px 4px rgba(0,0,0,.12); }

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
    return (
        gr.update(visible=True),
        gr.update(visible=False),
        [],
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
                    "每条回答均**标注引用来源**，遇急症关键词直接提示 **拨打 120**。\n"
                    "💡 可以直接在回答消息底部点击 👍 / 👎 提交反馈。"
                )
            back_btn = gr.Button("← 返回首页", size="sm", variant="secondary")
            chatbot = gr.Chatbot(
                type="messages",
                sanitize_html=False,
                height=520,
                avatar_images=(USER_AVATAR, BOT_AVATAR),
            )
            gr.ChatInterface(
                fn=respond,
                type="messages",
                title="",
                description="输入你的用药问题（例如：布洛芬和阿司匹林能一起吃吗？咳嗽用什么药？）",
                chatbot=chatbot,
            )
            gr.Markdown(
                "---\n"
                "*免责声明：系统回答仅供学习参考，不构成医疗建议。用药请遵医嘱，如有不适请及时就医。*\n"
                "*数据来源：《本草纲目》、国家基本药物处方集、国家基本药物临床应用指南。*"
            )

        # 事件绑定：进入聊天
        enter_btn.click(
            _enter_chat,
            inputs=None,
            outputs=[landing_page, chat_page],
        )
        # 返回首页
        back_btn.click(
            _back_home,
            inputs=None,
            outputs=[landing_page, chat_page, chatbot],
        )
    return demo


if __name__ == "__main__":
    build_ui().launch(server_name="0.0.0.0", server_port=7860)
