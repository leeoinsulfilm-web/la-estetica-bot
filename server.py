#!/usr/bin/env python3
"""
LUCAS — L.A Estética Automotiva
Webhook Server — uAZAPIGO + Claude API
Fábrica de Agentes | TIME DE DESENVOLVIMENTO
"""

import os, re, time, json, random, threading
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify
import anthropic
import requests

# ──────────────────────────────────────────────
# CONFIG — Railway injeta via variáveis de ambiente
# ──────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
UAZAPI_SERVER_URL = os.environ.get("UAZAPI_SERVER_URL", "https://strongtime.uazapi.com")
UAZAPI_TOKEN      = os.environ.get("UAZAPI_TOKEN", "")
UAZAPI_INSTANCE   = os.environ.get("UAZAPI_INSTANCE", "la-estetica")
WHATSAPP_NUMBER   = os.environ.get("WHATSAPP_NUMBER", "5519999037491")
PORT              = int(os.environ.get("PORT", 8080))

# ──────────────────────────────────────────────
# LOGGING — flush imediato para Railway
# ──────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ──────────────────────────────────────────────
# SYSTEM PROMPT — embutido via env ou arquivo
# ──────────────────────────────────────────────
def load_system_prompt() -> str:
    # 1. Variável de ambiente (Railway — mais robusto)
    env_prompt = os.environ.get("SYSTEM_PROMPT", "")
    if env_prompt:
        return env_prompt.strip()

    # 2. Arquivo local
    for candidate in [
        Path(__file__).parent / "PROMPT_SISTEMA.md",
        Path(__file__).parent.parent / "PROMPT_SISTEMA.md",
    ]:
        if candidate.exists():
            content = candidate.read_text(encoding="utf-8")
            lines = [l for l in content.split("\n")
                     if not l.startswith("# PROMPT SISTEMA")
                     and not l.startswith("# L.A")
                     and not l.startswith("# Gerado")]
            return "\n".join(lines).strip()

    return "Você é Lucas, da L.A Estética Automotiva em Leme SP. Atenda com naturalidade no WhatsApp."

SYSTEM_PROMPT = load_system_prompt()

# ──────────────────────────────────────────────
# CLAUDE CLIENT
# ──────────────────────────────────────────────
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ──────────────────────────────────────────────
# HISTÓRICO DE CONVERSAS (em memória, thread-safe)
# Max 20 mensagens por contato, TTL 4 horas
# ──────────────────────────────────────────────
_lock          = threading.Lock()
conversations  : dict[str, list[dict]] = {}
last_activity  : dict[str, float]      = {}
HISTORY_MAX    = 20
HISTORY_TTL    = 4 * 3600

def get_history(phone: str) -> list[dict]:
    with _lock:
        now = time.time()
        if phone in last_activity and (now - last_activity[phone]) > HISTORY_TTL:
            conversations.pop(phone, None)
            last_activity.pop(phone, None)
        return list(conversations.get(phone, []))

def add_to_history(phone: str, role: str, content: str):
    with _lock:
        if phone not in conversations:
            conversations[phone] = []
        conversations[phone].append({"role": role, "content": content})
        if len(conversations[phone]) > HISTORY_MAX:
            conversations[phone] = conversations[phone][-HISTORY_MAX:]
        last_activity[phone] = time.time()

# ──────────────────────────────────────────────
# HUMANIZAÇÃO — balões + delay de digitação
# ──────────────────────────────────────────────
def split_balloons(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r'\n\n+', text) if p.strip()]
    parts = []
    for para in paragraphs:
        if len(para) <= 120:
            if len(para) < 12 and parts:
                parts[-1] += " " + para
            else:
                parts.append(para)
        else:
            sentences = re.split(r'(?<=[.!?])\s+', para)
            current = ""
            for s in sentences:
                if len(current) + len(s) < 120:
                    current = (current + " " + s).strip()
                else:
                    if current:
                        parts.append(current)
                    current = s
            if current:
                parts.append(current)
    return parts if parts else [text]

def typing_delay_ms(text: str) -> int:
    return min(4500, max(1200, len(text) * 45))

# ──────────────────────────────────────────────
# uAZAPIGO — ENVIO DE MENSAGENS
# ──────────────────────────────────────────────
def normalize_phone(raw: str) -> str:
    digits = re.sub(r'\D', '', raw)
    return digits if digits.startswith('55') else f'55{digits}'

def uazapi_headers() -> dict:
    return {"Content-Type": "application/json", "token": UAZAPI_TOKEN}

def send_message(phone: str, text: str, delay_ms: int = 1500) -> bool:
    number = normalize_phone(phone)
    url    = f"{UAZAPI_SERVER_URL}/send/text"
    payload = {"number": number, "text": text, "delay": delay_ms}
    try:
        r = requests.post(url, json=payload, headers=uazapi_headers(), timeout=20)
        if not r.ok:
            log(f"SEND ERRO {r.status_code}: {r.text[:200]}")
            return False
        return True
    except Exception as e:
        log(f"SEND EXCEPTION: {e}")
        return False

def send_human_reply(phone: str, reply: str):
    balloons = split_balloons(reply)
    for i, balloon in enumerate(balloons):
        delay = typing_delay_ms(balloon)
        send_message(phone, balloon, delay_ms=delay)
        if i < len(balloons) - 1:
            pause = delay + 1200 + random.randint(0, 1500)
            time.sleep(pause / 1000)

# ──────────────────────────────────────────────
# uAZAPIGO — STATUS E WEBHOOK
# ──────────────────────────────────────────────
def get_instance_status() -> dict:
    try:
        r = requests.get(f"{UAZAPI_SERVER_URL}/instance/status",
                         headers=uazapi_headers(), timeout=10)
        return r.json() if r.ok else {"error": r.text[:200]}
    except Exception as e:
        return {"error": str(e)}

def configure_webhook(webhook_url: str) -> dict:
    payload = {
        "url": webhook_url,
        "enabled": True,
        "events": ["messages"],
        "excludeMessages": ["wasSentByApi"]
    }
    try:
        r = requests.post(f"{UAZAPI_SERVER_URL}/webhook",
                          json=payload, headers=uazapi_headers(), timeout=15)
        return r.json() if r.ok else {"error": r.text[:200]}
    except Exception as e:
        return {"error": str(e)}

# ──────────────────────────────────────────────
# CLAUDE — GERAR RESPOSTA
# ──────────────────────────────────────────────
def generate_reply(phone: str, user_message: str) -> str:
    add_to_history(phone, "user", user_message)
    messages = get_history(phone)
    try:
        response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=messages
        )
        reply = response.content[0].text
        add_to_history(phone, "assistant", reply)
        return reply
    except Exception as e:
        log(f"CLAUDE ERRO: {e}")
        return "Oi! Tô com um probleminha técnico agora. Me manda mensagem em alguns minutos 😊"

# ──────────────────────────────────────────────
# PARSE DO WEBHOOK uAZAPIGO (multi-formato)
# ──────────────────────────────────────────────
def parse_webhook(body: dict) -> dict | None:
    phone        = ""
    text         = ""
    from_me      = False
    is_group     = False
    contact_name = ""

    # Formato uAZAPIGO GO principal
    go_msg = body.get("message")
    if isinstance(go_msg, dict):
        phone        = str(go_msg.get("chatid") or go_msg.get("sender") or "")
        contact_name = str(go_msg.get("senderName") or go_msg.get("pushName") or "")
        from_me      = bool(go_msg.get("fromMe", False))
        text         = str(go_msg.get("body") or go_msg.get("text") or "")
        msg_type     = str(go_msg.get("type") or "")
        if msg_type in ("audio", "ptt", "image", "video", "document", "sticker"):
            return None

    # Formato plano (fallback)
    if not phone and body.get("phone"):
        phone        = str(body.get("phone") or "")
        contact_name = str(body.get("pushName") or body.get("name") or "")
        text         = str(body.get("message") or body.get("text") or body.get("body") or "")
        from_me      = bool(body.get("fromMe", False))
        is_group     = bool(body.get("isGroup") or body.get("isGroupMsg", False))

    # Formato Evolution API
    if not phone:
        data = body.get("data") or body
        key  = data.get("key") if isinstance(data, dict) else None
        if isinstance(key, dict):
            phone   = str(key.get("remoteJid") or "").replace("@s.whatsapp.net", "")
            from_me = bool(key.get("fromMe", False))
        if isinstance(data, dict):
            contact_name = str(data.get("pushName") or "")
            msg_content  = data.get("message") or {}
            if isinstance(msg_content, dict):
                text = str(
                    msg_content.get("conversation") or
                    (msg_content.get("extendedTextMessage") or {}).get("text") or ""
                )

    phone    = re.sub(r'\D', '', phone)
    is_group = is_group or "@g.us" in str(body) or len(phone) > 13

    if not phone or not text or from_me or is_group:
        return None

    return {"phone": phone, "text": text.strip(), "name": contact_name}

# ──────────────────────────────────────────────
# FLASK APP
# ──────────────────────────────────────────────
app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health():
    """Health check para Railway."""
    return jsonify({"status": "ok"}), 200

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "agent": "Lucas — L.A Estética Automotiva",
        "status": "online",
        "prompt_loaded": len(SYSTEM_PROMPT) > 100,
        "conversations_ativas": len(conversations),
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    body   = request.get_json(silent=True) or {}
    log(f"WEBHOOK_RAW: {json.dumps(body)[:800]}")

    parsed = parse_webhook(body)
    if not parsed:
        log(f"WEBHOOK_IGNORADO (parse=None) keys={list(body.keys())}")
        return jsonify({"received": True})

    phone = parsed["phone"]
    text  = parsed["text"]
    name  = parsed["name"] or "Cliente"
    log(f"MSG de {name} ({phone}): {text[:100]}")

    def process():
        reply = generate_reply(phone, text)
        log(f"REPLY → {phone}: {reply[:100]}")
        send_human_reply(phone, reply)

    threading.Thread(target=process, daemon=True).start()
    return jsonify({"received": True})

@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "server": UAZAPI_SERVER_URL,
        "instance": UAZAPI_INSTANCE,
        "number": WHATSAPP_NUMBER,
        "prompt_loaded": len(SYSTEM_PROMPT) > 100,
        "conversations_ativas": len(conversations),
        "uazapi": get_instance_status()
    })

@app.route("/test-claude", methods=["GET"])
def test_claude():
    """Testa a Claude API diretamente."""
    try:
        r = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=30,
            messages=[{"role": "user", "content": "diga só: ok"}]
        )
        return jsonify({"ok": True, "reply": r.content[0].text, "key_prefix": ANTHROPIC_API_KEY[:20]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "key_prefix": ANTHROPIC_API_KEY[:20]})

@app.route("/test-send", methods=["POST"])
def test_send():
    """Testa envio direto via UazAPI — debug."""
    data   = request.get_json(silent=True) or {}
    number = data.get("number", WHATSAPP_NUMBER)
    text   = data.get("text", "teste de envio do Lucas 🚗")
    ok     = send_message(number, text, delay_ms=500)
    return jsonify({"sent": ok, "number": number, "token_ok": bool(UAZAPI_TOKEN)})

@app.route("/setup-webhook", methods=["POST"])
def setup_webhook():
    data = request.get_json(silent=True) or {}
    webhook_url = data.get("webhook_url")
    if not webhook_url:
        return jsonify({"error": "Informe webhook_url no body"}), 400
    result = configure_webhook(webhook_url)
    log(f"Webhook configurado: {webhook_url}")
    return jsonify({"ok": True, "result": result})

# ──────────────────────────────────────────────
# STARTUP LOG
# ──────────────────────────────────────────────
log("═" * 54)
log("  LUCAS — L.A Estética Automotiva")
log("  Webhook Server | uAZAPIGO + Claude API")
log("═" * 54)
log(f"  uAZAPIGO:  {UAZAPI_SERVER_URL}")
log(f"  Instância: {UAZAPI_INSTANCE}")
log(f"  Número:    {WHATSAPP_NUMBER}")
log(f"  Token:     {'✅ OK' if UAZAPI_TOKEN else '❌ AUSENTE'}")
log(f"  Claude:    {'✅ OK' if ANTHROPIC_API_KEY else '❌ AUSENTE'}")
log(f"  Prompt:    {'✅ ' + str(len(SYSTEM_PROMPT)) + ' chars' if len(SYSTEM_PROMPT) > 100 else '❌ AUSENTE'}")
log("═" * 54)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
