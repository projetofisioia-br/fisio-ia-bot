import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V8.0 - Sistema Integrado PRO Ativo"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "").strip()
API_KEY_IA = os.environ.get("API_KEY_IA", "").strip()
MONGO_URI = os.environ.get("MONGO_URI", "").strip()
TOKEN_PAYMENT = os.environ.get("TOKEN_PAYMENT", "").strip()

MODELO = "gemini-1.5-flash"

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# --- BANCO DE DADOS ---
client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
usuarios_coll = db['usuarios']
pacientes_coll = db['pacientes']

# --- PROMPT ---
PROMPT_SISTEMA = """
Atue como um Fisioterapeuta PhD. Forneça uma análise técnica estruturada em 15 tópicos obrigatórios:
(Definição, Anatomia/Biomecânica, Etiologia, Sintomas, Raciocínio, Avaliação, Testes, Diagnóstico Diferencial, Exames, Classificação, Conduta, Protocolo Atleta, Algoritmo, Red Flags e Evidências).
Use linguagem científica de alto nível e formatação Markdown clara.
"""

# --- MENU ---
def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👤 Novo Paciente", callback_data="novo_paciente"),
        types.InlineKeyboardButton("📂 Histórico de Pacientes", callback_data="ver_historico"),
        types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica"),
        types.InlineKeyboardButton("💎 Planos de Acesso Pro", callback_data="planos")
    )
    return markup

# --- IA COM CONTROLE DE PLANO ---
def chamar_ia(message, texto_usuario, nome_paciente=None):
    user_id = message.from_user.id
    user_data = usuarios_coll.find_one({"user_id": user_id}) or {"plano": "FREE", "consultas": 0}

    if user_data.get("plano") != "PRO" and user_data.get("consultas", 0) >= 3:
        bot.send_message(message.chat.id, "⚠️ Limite FREE atingido. Faça upgrade para o Pro.", reply_markup=menu_principal())
        return

    aguarde = bot.send_message(message.chat.id, "🧠 Processando análise clínica avançada...")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"

    payload = {
        "contents": [{"parts": [{"text": f"{PROMPT_SISTEMA}\n\nCaso clínico: {texto_usuario}"}]}],
        "generationConfig": {
            "temperature": 0.7,
            "topP": 0.8
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=120)
        res_data = response.json()

        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']

            # salvar paciente
            if nome_paciente:
                pacientes_coll.update_one(
                    {"profissional_id": user_id, "nome": nome_paciente},
                    {"$set": {"ultima_analise": analise, "data": time.strftime("%d/%m/%Y")}},
                    upsert=True
                )

            # atualizar contador
            usuarios_coll.update_one(
                {"user_id": user_id},
                {"$inc": {"consultas": 1}},
                upsert=True
            )

            bot.delete_message(message.chat.id, aguarde.message_id)

            for i in range(0, len(analise), 4000):
                bot.send_message(message.chat.id, analise[i:i+4000], parse_mode="Markdown")

            bot.send_message(message.chat.id, "✅ Análise concluída.", reply_markup=menu_principal())

        else:
            erro = res_data.get('error', {}).get('message', 'Erro desconhecido da IA')
            bot.edit_message_text(f"⚠️ IA: {erro}", message.chat.id, aguarde.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Erro: {str(e)}", message.chat.id, aguarde.message_id)

# --- CALLBACKS ---
@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    bot.answer_callback_query(call.id)

    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
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
        try:
            bot.send_invoice(
                chat_id=call.message.chat.id,
                title="MestreFisio PhD Pro 💎",
                description="Acesso ilimitado às análises clínicas",
                provider_token=TOKEN_PAYMENT,
                currency="BRL",
                prices=[types.LabeledPrice("Plano PRO", 5990)],
                invoice_payload="pro_access",
                start_parameter="pro_access"
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Erro no pagamento:\n{str(e)}")

# --- FLUXO PACIENTE ---
def obter_nome(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: {nome}\nDescreva o quadro clínico:")
    bot.register_next_step_handler(msg, lambda m: chamar_ia(m, m.text, nome))

# --- START ---
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "🚀 MestreFisio V8.0 - Sistema Clínico Inteligente", reply_markup=menu_principal())

# --- EXECUÇÃO ---
if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    time.sleep(2)
    bot.infinity_polling(timeout=120, long_polling_timeout=60)
