import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V5.8 - Pagamento Ativo"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM").strip()
API_KEY_IA = os.environ.get("API_KEY_IA").strip()
MONGO_URI = os.environ.get("MONGO_URI").strip()

# ALTERADO PARA TOKEN_PAYMENT CONFORME SOLICITADO
TOKEN_PAYMENT = os.environ.get("TOKEN_PAYMENT", "").strip() 

MODELO = "gemini-1.5-flash"
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# --- LÓGICA DE PAGAMENTO (PRIORIDADE) ---
@bot.callback_query_handler(func=lambda call: call.data == "planos")
def enviar_fatura(call):
    lang = 'en' if call.from_user.language_code and call.from_user.language_code.startswith('en') else 'pt'
    moeda = "USD" if lang == 'en' else "BRL"
    preco = 1990 if lang == 'en' else 5990 # R$ 59,90
    
    try:
        bot.send_invoice(
            call.message.chat.id,
            title="MestreFisio PhD Pro 💎",
            description="Acesso ilimitado e suporte clínico PhD.",
            provider_token=TOKEN_PAYMENT, # Usando a nova chave
            currency=moeda,
            prices=[types.LabeledPrice(label="Assinatura Pro", amount=preco)],
            start_parameter="mestre-fisio-pro",
            payload="pro_access_global"
        )
        bot.answer_callback_query(call.id)
    except Exception as e:
        # Se der erro, ele vai imprimir exatamente o que o Telegram rejeitou
        bot.send_message(call.message.chat.id, f"❌ Erro na Fatura: {e}")

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout_confirm(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def pagamento_sucesso(m):
    # Atualiza o plano no MongoDB
    client = MongoClient(MONGO_URI)
    db = client['mestre_fisio_db']
    db.usuarios.update_one({"user_id": m.from_user.id}, {"$set": {"plano": "PRO"}}, upsert=True)
    bot.send_message(m.chat.id, "✅ Pagamento confirmado! Acesso PhD Pro liberado!")

# --- CALLBACK GERAL E IA (O RESTANTE DO SEU CÓDIGO) ---
@bot.callback_query_handler(func=lambda call: True)
def callback_geral(call):
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual condição deseja analisar?")
        bot.register_next_step_handler(msg, processar_ia_direta)
    elif call.data == "ajuda_btn":
        bot.send_message(call.message.chat.id, "⚖️ Aviso Legal: Uso profissional apenas.")
    bot.answer_callback_query(call.id)

# (Inclua aqui as funções chamar_gemini e as demais que você já possui)

if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    bot.infinity_polling(timeout=120)
