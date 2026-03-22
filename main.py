import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- SERVIDOR WEB PARA O RENDER ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V5.9 - Sistema Ativo"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "").strip()
API_KEY_IA = os.environ.get("API_KEY_IA", "").strip()
MONGO_URI = os.environ.get("MONGO_URI", "").strip()
TOKEN_PAYMENT = os.environ.get("TOKEN_PAYMENT", "").strip()

MODELO = "gemini-1.5-flash"
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# Conexão Banco de Dados
client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
usuarios_coll = db['usuarios']

# --- LÓGICA DE PAGAMENTO ---
@bot.callback_query_handler(func=lambda call: call.data == "planos")
def enviar_fatura(call):
    try:
        if not TOKEN_PAYMENT:
            bot.send_message(call.message.chat.id, "❌ Erro: Chave TOKEN_PAYMENT não configurada no Render.")
            return

        bot.send_invoice(
            call.message.chat.id,
            title="MestreFisio PhD Pro 💎",
            description="Acesso ilimitado e suporte clínico PhD.",
            provider_token=TOKEN_PAYMENT,
            currency="BRL",
            prices=[types.LabeledPrice(label="Assinatura Pro", amount=5990)], # R$ 59,90
            payload="pro_access",
            start_parameter="mestre-fisio-pro"
        )
        bot.answer_callback_query(call.id)
    except Exception as e:
        bot.send_message(call.message.chat.id, f"⚠️ Erro ao gerar fatura: {e}")

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout_confirm(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def pagamento_sucesso(m):
    usuarios_coll.update_one({"user_id": m.from_user.id}, {"$set": {"plano": "PRO"}}, upsert=True)
    bot.send_message(m.chat.id, "✅ Pagamento confirmado! Acesso PhD Pro liberado!")

# --- MENU E COMANDOS ---
def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👤 Novo Paciente", callback_data="novo_paciente"),
        types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica"),
        types.InlineKeyboardButton("💎 Planos de Acesso Pro", callback_data="planos"),
        types.InlineKeyboardButton("⚖️ Ajuda e Termos", callback_data="ajuda")
    )
    return markup

@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "🚀 **MestreFisio PhD**\nSistema de alta performance para análises clínicas.", reply_markup=menu_principal())

@bot.callback_query_handler(func=lambda call: True)
def callback_geral(call):
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Digite o nome do paciente:")
        bot.register_next_step_handler(msg, lambda m: bot.send_message(m.chat.id, f"Paciente {m.text} registrado. Descreva o quadro clínico:"))
    elif call.data == "ajuda":
        bot.send_message(call.message.chat.id, "⚖️ Uso profissional. Consulte sempre os termos de uso.")
    bot.answer_callback_query(call.id)

if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    bot.infinity_polling(timeout=120)
