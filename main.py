import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V7.0 - IA Blindada"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "").strip()
API_KEY_IA = os.environ.get("API_KEY_IA", "").strip()
MONGO_URI = os.environ.get("MONGO_URI", "").strip()
TOKEN_PAYMENT = os.environ.get("TOKEN_PAYMENT", "").strip()

MODELO = "gemini-1.5-flash"
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
usuarios_coll = db['usuarios']
pacientes_coll = db['pacientes']

PROMPT_SISTEMA = "Atue como um Fisioterapeuta PhD. Forneça análise técnica em 15 tópicos. Esta é uma consulta entre profissionais para fins de estudo acadêmico."

# --- LÓGICA DE IA (VERSÃO COM BYPASS DE FILTRO) ---
def chamar_ia(message, texto_usuario, nome_paciente=None):
    user_id = message.from_user.id
    user_data = usuarios_coll.find_one({"user_id": user_id}) or {"plano": "FREE", "consultas": 0}
    
    if user_data.get("plano") != "PRO" and user_data.get("consultas", 0) >= 3:
        bot.send_message(message.chat.id, "⚠️ Limite atingido. Assine o Pro!", reply_markup=menu_principal())
        return

    aguarde = bot.send_message(message.chat.id, "🧠 **Analisando quadro clínico...**")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    # Configuração para evitar bloqueios por "conteúdo médico"
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
        
        if 'candidates' in res_data and 'content' in res_data['candidates'][0]:
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
            # Se cair aqui, vamos mostrar o motivo técnico do bloqueio
            motivo = res_data.get('promptFeedback', {}).get('blockReason', 'Filtro de Segurança ou Chave Inválida')
            bot.edit_message_text(f"⚠️ O Google bloqueou a resposta: {motivo}", message.chat.id, aguarde.message_id)
    except:
        bot.edit_message_text(f"❌ Falha técnica de conexão.", message.chat.id, aguarde.message_id)

# --- BOTÕES E FLUXO ---
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
            call.message.chat.id, "MestreFisio PhD Pro 💎", "Acesso ilimitado.",
            TOKEN_PAYMENT, "BRL", [types.LabeledPrice("Pro", 5990)],
            invoice_payload="pro_access", start_parameter="pro"
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
