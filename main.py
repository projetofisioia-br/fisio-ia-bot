import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V5.0 - Sistema Inteligente PRO Ativo"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "").strip()
API_KEY_IA = os.environ.get("API_KEY_IA", "").strip()
MODELO = "gemini-2.5-flash"
MONGO_URI = os.environ.get("MONGO_URI", "").strip()
TOKEN_PAYMENT = os.environ.get("TOKEN_PAYMENT", "").strip()

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# --- BANCO ---
client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
pacientes_coll = db['pacientes']
usuarios_coll = db['usuarios']

# --- PROMPT ---
PROMPT_SISTEMA = """
Atue como um Fisioterapeuta PhD. Forneça uma análise técnica estruturada em 15 tópicos obrigatórios (Definição, Anatomia/Biomecânica, Etiologia, Sintomas, Raciocínio, Avaliação, Testes, Diagnóstico Diferencial, Exames, Classificação, Conduta, Protocolo Atleta, Algoritmo, Red Flags e Evidências). 
Use linguagem científica de alto nível e formatação Markdown clara.
"""

# --- MENU ---
def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👤 Novo Paciente", callback_data="novo_paciente"),
        types.InlineKeyboardButton("🧠 Atualizar Paciente", callback_data="atualizar_paciente"),
        types.InlineKeyboardButton("📂 Histórico de Pacientes", callback_data="ver_historico"),
        types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica"),
        types.InlineKeyboardButton("💎 Planos de Acesso Pro", callback_data="planos")
    )
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(
        message.chat.id,
        "🚀 **MestreFisio V5.0 Especialista**\nSistema clínico com memória evolutiva.",
        reply_markup=menu_principal()
    )

# --- CALLBACK ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)

    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)

    elif call.data == "atualizar_paciente":
        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))
        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Nenhum paciente cadastrado.")
            return

        markup = types.InlineKeyboardMarkup()
        for p in pacientes:
            markup.add(types.InlineKeyboardButton(p['nome'], callback_data=f"paciente_{p['nome']}"))

        bot.send_message(call.message.chat.id, "Selecione o paciente:", reply_markup=markup)

    elif call.data.startswith("paciente_"):
        nome = call.data.replace("paciente_", "")
        msg = bot.send_message(call.message.chat.id, f"✍️ Atualize o quadro clínico de {nome}:")
        bot.register_next_step_handler(msg, processar_ia_paciente, nome)

    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual condição deseja analisar hoje?")
        bot.register_next_step_handler(msg, processar_ia_direta)

    elif call.data == "ver_historico":
        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))
        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Histórico vazio.")
        else:
            for p in pacientes:
                evolucoes = p.get("evolucoes", [])
                bot.send_message(
                    call.message.chat.id,
                    f"📂 **{p['nome']}**\nEvoluções: {len(evolucoes)}"
                )

    elif call.data == "planos":
        try:
            bot.send_invoice(
                chat_id=call.message.chat.id,
                title="MestreFisio PhD Pro 💎",
                description="Acesso ilimitado às análises.",
                provider_token=TOKEN_PAYMENT,
                currency="BRL",
                prices=[types.LabeledPrice("Assinatura Pro", 5990)],
                invoice_payload="pro_access",
                start_parameter="pro_access"
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Erro no pagamento:\n{str(e)}")

# --- PAGAMENTO ---
@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def pagamento_confirmado(message):
    user_id = message.from_user.id

    usuarios_coll.update_one(
        {"user_id": user_id},
        {"$set": {"plano": "PRO", "consultas": 0}},
        upsert=True
    )

    bot.send_message(
        message.chat.id,
        "💎 Pagamento aprovado! PRO liberado 🚀",
        reply_markup=menu_principal()
    )

# --- FLUXO PACIENTE ---
def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: {nome}\nDescreva o quadro clínico:")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):
    prompt = f"{PROMPT_SISTEMA}\n\nAnalise detalhadamente o caso do paciente {nome}: {message.text}"
    chamar_gemini(message, prompt, nome)

def processar_ia_direta(message):
    prompt = f"{PROMPT_SISTEMA}\n\nForneça uma explanação técnica PhD sobre: {message.text}"
    chamar_gemini(message, prompt)

# --- IA ---
def chamar_gemini(message, prompt, nome_paciente=None):
    user_id = message.from_user.id

    user_data = usuarios_coll.find_one({"user_id": user_id}) or {"plano": "FREE", "consultas": 0}

    if user_data.get("plano") != "PRO" and user_data.get("consultas", 0) >= 3:
        bot.send_message(message.chat.id, "⚠️ Limite FREE atingido. Assine o PRO.", reply_markup=menu_principal())
        return

    aguarde = bot.send_message(message.chat.id, "🧠 Construindo raciocínio clínico...")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"

    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=400)
        res_data = response.json()

        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']

            if nome_paciente:
                pacientes_coll.update_one(
                    {"profissional_id": user_id, "nome": nome_paciente},
                    {
                        "$push": {
                            "evolucoes": {
                                "data": time.strftime("%d/%m/%Y %H:%M"),
                                "relato": message.text,
                                "analise": analise
                            }
                        },
                        "$set": {"ultima_atualizacao": time.strftime("%d/%m/%Y")}
                    },
                    upsert=True
                )

            usuarios_coll.update_one(
                {"user_id": user_id},
                {"$inc": {"consultas": 1}},
                upsert=True
            )

            bot.delete_message(message.chat.id, aguarde.message_id)

            partes = [analise[i:i+1500] for i in range(0, len(analise), 1500)]

            for p in partes:
                try:
                    bot.send_message(message.chat.id, p, parse_mode="Markdown")
                    time.sleep(1.2)
                except:
                    bot.send_message(message.chat.id, p)

            bot.send_message(message.chat.id, "✅ Análise Finalizada", reply_markup=menu_principal())

        else:
            bot.send_message(message.chat.id, "⚠️ IA não respondeu corretamente.")

    except Exception as e:
        print(f"Erro: {e}")
        bot.send_message(message.chat.id, "❌ Falha na conexão.")

# --- EXECUÇÃO ---
if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    time.sleep(2)
    bot.infinity_polling(timeout=120, long_polling_timeout=60)
