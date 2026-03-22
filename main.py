import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V7.7 - Online"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "").strip()
API_KEY_IA = os.environ.get("API_KEY_IA", "").strip()
MONGO_URI = os.environ.get("MONGO_URI", "").strip()
TOKEN_PAYMENT = os.environ.get("TOKEN_PAYMENT", "").strip()

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
usuarios_coll = db['usuarios']
pacientes_coll = db['pacientes']

PROMPT_SISTEMA = "Atue como um Fisioterapeuta PhD. Forneça análise biomecânica técnica."

# --- LÓGICA DE IA (AJUSTE DE MODELO PARA API v1) ---
def chamar_ia(message, texto_usuario, nome_paciente=None):
    user_id = message.from_user.id
    user_data = usuarios_coll.find_one({"user_id": user_id}) or {"plano": "FREE", "consultas": 0}
    
    if user_data.get("plano") != "PRO" and user_data.get("consultas", 0) >= 3:
        bot.send_message(message.chat.id, "⚠️ Limite atingido. Assine o Pro!", reply_markup=menu_principal())
        return

    aguarde = bot.send_message(message.chat.id, "🧠 **Analisando quadro clínico...**")
    
    # URL e Modelo ajustados para a versão mais estável da API
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY_IA}"
    
    payload = {
        "contents": [{"parts": [{"text": f"{PROMPT_SISTEMA}\n\nPERGUNTA: {texto_usuario}"}]}],
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }

    try:
        response = requests.post(url, json=payload, timeout=60)
        res_data = response.json()
        
        # Se o flash falhar, tentamos o pro automaticamente (fallback)
        if 'error' in res_data and 'not found' in res_data['error']['message']:
            url_alt = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={API_KEY_IA}"
            response = requests.post(url_alt, json=payload, timeout=60)
            res_data = response.json()

        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            
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
            erro_txt = res_data.get('error', {}).get('message', 'Erro de resposta')
            bot.edit_message_text(f"⚠️ Nota da IA: {erro_txt}", message.chat.id, aguarde.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Falha técnica: {str(e)}", message.chat.id, aguarde.message_id)

# --- MENUS E PAGAMENTO ---
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
        bot.register_next_step_handler(msg, obter_nome)
    elif call.data == "ver_historico":
        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))
        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Histórico vazio.")
        else:
            txt = "📂 **Seus Pacientes:**\n" + "\n".join([f"• {p['nome']} ({p['data']})" for p in pacientes])
            bot.send_message(call.message.chat.id, txt)
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual sua dúvida?")
        bot.register_next_step_handler(msg, lambda m: chamar_ia(m, m.text))
    elif call.data == "planos":
        bot.send_invoice(
            call.message.chat.id, 
            title="MestreFisio PhD Pro 💎", 
            description="Acesso ilimitado às análises clínicas.",
            provider_token=TOKEN_PAYMENT,
            currency="BRL",
            prices=[types.LabeledPrice("Assinatura Pro", 5990)],
            invoice_payload="pro_access",
            start_parameter="pro_access"
        )
    bot.answer_callback_query(call.id)

def obter_nome(m):
    nome = m.text.upper()
    msg = bot.send_message(m.chat.id, f"✅ Paciente {nome}\nDescreva o quadro:")
    bot.register_next_step_handler(msg, lambda m2: chamar_ia(m2, m2.text, nome))

@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "🚀 **MestreFisio PhD**", reply_markup=menu_principal())

if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling(timeout=120)
