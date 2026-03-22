import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V6.7 - IA Estável"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "").strip()
API_KEY_IA = os.environ.get("API_KEY_IA", "").strip()
MONGO_URI = os.environ.get("MONGO_URI", "").strip()
TOKEN_PAYMENT = os.environ.get("TOKEN_PAYMENT", "").strip()

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# Banco de Dados
client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
usuarios_coll = db['usuarios']
pacientes_coll = db['pacientes']

PROMPT_SISTEMA = "Atue como um Fisioterapeuta PhD. Forneça análise em 15 tópicos técnicos estruturados."

# --- LÓGICA DE IA (URL DIRETA) ---
def chamar_ia(message, texto_usuario, nome_paciente=None):
    user_id = message.from_user.id
    user_data = usuarios_coll.find_one({"user_id": user_id}) or {"plano": "FREE", "consultas": 0}
    
    if user_data.get("plano") != "PRO" and user_data.get("consultas", 0) >= 3:
        bot.send_message(message.chat.id, "⚠️ Limite atingido. Assine o Pro para continuar.", reply_markup=menu_principal())
        return

    aguarde = bot.send_message(message.chat.id, "🧠 **Gerando raciocínio clínico PhD...**")
    
    # URL DIRETA E SEM VARIÁVEIS DE NOME DE MODELO (MAIS SEGURO)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY_IA}"
    
    payload = {
        "contents": [{
            "parts": [{"text": f"{PROMPT_SISTEMA}\n\nPERGUNTA: {texto_usuario}"}]
        }]
    }

    try:
        # Request com Timeout estendido
        response = requests.post(url, json=payload, timeout=90)
        res_data = response.json()
        
        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            
            # Salva no Histórico do Profissional
            if nome_paciente:
                pacientes_coll.update_one(
                    {"profissional_id": user_id, "nome": nome_paciente.upper()},
                    {"$set": {"ultima_analise": analise, "data": time.strftime("%d/%m/%Y")}},
                    upsert=True
                )
            
            usuarios_coll.update_one({"user_id": user_id}, {"$inc": {"consultas": 1}}, upsert=True)
            bot.delete_message(message.chat.id, aguarde.message_id)
            
            for i in range(0, len(analise), 4000):
                bot.send_message(message.chat.id, analise[i:i+4000], parse_mode="Markdown")
        else:
            erro_msg = res_data.get('error', {}).get('message', 'Erro na resposta do Google')
            bot.edit_message_text(f"⚠️ Resposta do Google: {erro_msg}", message.chat.id, aguarde.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Falha de conexão: {str(e)}", message.chat.id, aguarde.message_id)

# --- MENUS E BOTÕES ---
def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👤 Novo Paciente", callback_data="novo_paciente"),
        types.InlineKeyboardButton("📂 Histórico de Pacientes", callback_data="ver_historico"),
        types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica"),
        types.InlineKeyboardButton("💎 Planos de Acesso Pro", callback_data="planos")
    )
    return markup

@bot.callback_query_handler(func=lambda call: True)
def callback_geral(call):
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do Paciente:")
        bot.register_next_step_handler(msg, lambda m: bot.register_next_step_handler(
            bot.send_message(m.chat.id, f"✅ Paciente: {m.text.upper()}\nDescreva o quadro:"),
            lambda m2: chamar_ia(m2, m2.text, m.text.upper())
        ))
    elif call.data == "ver_historico":
        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))
        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Nenhum paciente no histórico.")
        else:
            msg_h = "📂 **Seus Pacientes:**\n"
            for p in pacientes: msg_h += f"• {p['nome']} ({p['data']})\n"
            bot.send_message(call.message.chat.id, msg_h)
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual sua dúvida?")
        bot.register_next_step_handler(msg, lambda m: chamar_ia(m, m.text))
    elif call.data == "planos":
        bot.send_invoice(
            call.message.chat.id, "MestreFisio PhD Pro 💎", "Acesso ilimitado.",
            TOKEN_PAYMENT, "BRL", [types.LabeledPrice("Pro", 5990)],
            invoice_payload="pro_access", start_parameter="pro"
        )
    bot.answer_callback_query(call.id)

@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "🚀 **MestreFisio PhD**", reply_markup=menu_principal())

if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    bot.infinity_polling(timeout=120)
