import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V6.0 - Online"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "").strip()
API_KEY_IA = os.environ.get("API_KEY_IA", "").strip()
MONGO_URI = os.environ.get("MONGO_URI", "").strip()
TOKEN_PAYMENT = os.environ.get("TOKEN_PAYMENT", "").strip()

MODELO = "gemini-1.5-flash"
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# Banco de Dados
client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
usuarios_coll = db['usuarios']

PROMPT_SISTEMA = "Atue como um Fisioterapeuta PhD. Forneça uma análise técnica estruturada em 15 tópicos..."

# --- LÓGICA DE PAGAMENTO (CORRIGIDA) ---
@bot.callback_query_handler(func=lambda call: call.data == "planos")
def enviar_fatura(call):
    try:
        bot.send_invoice(
            call.message.chat.id,
            title="MestreFisio PhD Pro 💎",
            description="Acesso ilimitado e suporte clínico PhD.",
            provider_token=TOKEN_PAYMENT,
            currency="BRL",
            prices=[types.LabeledPrice(label="Assinatura Pro", amount=5990)],
            invoice_payload="pro_access_payload", # NOME CORRIGIDO AQUI
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

# --- INTELIGÊNCIA ARTIFICIAL ---
def chamar_ia(message, texto_usuario):
    user_id = message.from_user.id
    user_data = usuarios_coll.find_one({"user_id": user_id})
    consultas = user_data.get("consultas", 0) if user_data else 0
    plano = user_data.get("plano", "FREE") if user_data else "FREE"

    if plano != "PRO" and consultas >= 3:
        bot.send_message(message.chat.id, "⚠️ **Limite Atingido!** Assine o Pro para continuar.", reply_markup=menu_principal())
        return

    aguarde = bot.send_message(message.chat.id, "🧠 **Analisando quadro clínico...**")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    try:
        payload = {"contents": [{"parts": [{"text": f"{PROMPT_SISTEMA}\n\n{texto_usuario}"}]}]}
        response = requests.post(url, json=payload, timeout=60)
        res_data = response.json()
        
        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            usuarios_coll.update_one({"user_id": user_id}, {"$inc": {"consultas": 1}}, upsert=True)
            bot.delete_message(message.chat.id, aguarde.message_id)
            for parte in [analise[i:i+1500] for i in range(0, len(analise), 1500)]:
                bot.send_message(message.chat.id, parte, parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, "⚠️ Erro na IA. Tente novamente.")
    except:
        bot.send_message(message.chat.id, "❌ Falha de conexão com a IA.")

# --- MENUS E COMANDOS ---
def menu_principal():
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(
        types.InlineKeyboardButton("👤 Novo Paciente", callback_data="novo_paciente"),
        types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica"),
        types.InlineKeyboardButton("💎 Planos de Acesso Pro", callback_data="planos")
    )
    return m

@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "🚀 **MestreFisio PhD**", reply_markup=menu_principal())

@bot.callback_query_handler(func=lambda call: True)
def callback_geral(call):
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
        bot.register_next_step_handler(msg, lambda m: bot.send_message(m.chat.id, f"Paciente {m.text} ok. Descreva o quadro:", 
            callback=bot.register_next_step_handler(msg, lambda m2: chamar_ia(m2, m2.text))))
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual sua dúvida?")
        bot.register_next_step_handler(msg, lambda m: chamar_ia(m, m.text))
    bot.answer_callback_query(call.id)

if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    bot.infinity_polling(timeout=120)
