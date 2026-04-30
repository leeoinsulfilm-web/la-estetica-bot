#!/bin/bash
# ═══════════════════════════════════════════════════════
# LUCAS — L.A Estética Automotiva
# Iniciar integração WhatsApp real com uAZAPIGO
# ═══════════════════════════════════════════════════════

set -e
cd "$(dirname "$0")"

source .env 2>/dev/null || true

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  LUCAS — L.A Estética Automotiva"
echo "  Integração WhatsApp Real — uAZAPIGO + Claude"
echo "═══════════════════════════════════════════════════════"

# Verificar variáveis obrigatórias
if [ -z "$ANTHROPIC_API_KEY" ] || [ "$ANTHROPIC_API_KEY" = "cole_sua_chave_aqui" ]; then
  echo ""
  echo "❌ ANTHROPIC_API_KEY não configurada."
  echo "   Edite o arquivo .env e cole sua chave Anthropic."
  exit 1
fi

if [ -z "$UAZAPI_TOKEN" ] || [ "$UAZAPI_TOKEN" = "cole_o_token_da_instancia_la-estetica_aqui" ]; then
  echo ""
  echo "❌ UAZAPI_TOKEN não configurado."
  echo "   Crie a instância 'la-estetica' no painel uAZAPIGO"
  echo "   e cole o token no arquivo .env"
  exit 1
fi

# Configurar ngrok auth se disponível
if [ -n "$NGROK_AUTH_TOKEN" ]; then
  ngrok config add-authtoken "$NGROK_AUTH_TOKEN" 2>/dev/null || true
fi

PORT=${PORT:-8766}

echo ""
echo "  ✅ Variáveis OK"
echo "  Iniciando servidor webhook na porta $PORT..."
echo ""

# Iniciar servidor webhook em background
python3 server.py &
SERVER_PID=$!
echo "  Servidor PID: $SERVER_PID"

# Esperar servidor subir
sleep 2

# Iniciar ngrok
echo ""
echo "  Iniciando ngrok para expor o webhook publicamente..."
ngrok http $PORT --log=stdout 2>/dev/null &
NGROK_PID=$!
echo "  ngrok PID: $NGROK_PID"

sleep 3

# Pegar URL pública do ngrok
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    tunnels = d.get('tunnels', [])
    for t in tunnels:
        if t.get('proto') == 'https':
            print(t['public_url'])
            break
except:
    pass
" 2>/dev/null)

if [ -z "$NGROK_URL" ]; then
  echo ""
  echo "  ⚠️  Não foi possível obter URL do ngrok automaticamente."
  echo "  Verifique: http://localhost:4040"
  echo ""
else
  WEBHOOK_URL="${NGROK_URL}/webhook"
  echo ""
  echo "═══════════════════════════════════════════════════════"
  echo "  ✅ TUDO RODANDO!"
  echo ""
  echo "  Webhook público: $WEBHOOK_URL"
  echo "  Status:          ${NGROK_URL}/status"
  echo "  QR Code:         ${NGROK_URL}/qrcode"
  echo ""
  echo "  Configurando webhook no uAZAPIGO automaticamente..."

  # Configurar webhook no uAZAPIGO
  RESULT=$(curl -s -X POST "http://localhost:${PORT}/setup-webhook" \
    -H "Content-Type: application/json" \
    -d "{\"webhook_url\": \"${WEBHOOK_URL}\"}")
  echo "  Resultado: $RESULT"
  echo ""
  echo "  ┌─────────────────────────────────────────────────┐"
  echo "  │  PRÓXIMOS PASSOS:                               │"
  echo "  │                                                   │"
  echo "  │  1. Abra: ${NGROK_URL}/qrcode"
  echo "  │  2. Escaneie com o celular do número:           │"
  echo "  │     ${WHATSAPP_NUMBER}                               │"
  echo "  │  3. WhatsApp conectado → Lucas já responde!      │"
  echo "  └─────────────────────────────────────────────────┘"
  echo "═══════════════════════════════════════════════════════"
fi

echo ""
echo "  Logs em tempo real abaixo (Ctrl+C para parar):"
echo "  ─────────────────────────────────────────────"
echo ""

# Aguardar (os processos background continuam rodando)
wait $SERVER_PID
