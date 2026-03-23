import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V5.0 - Memória Clínica Inteligente Ativa 🧠"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "").strip()
API_KEY_IA = os.environ.get("API_KEY_IA", "").strip()
MODELO = "gemini-2.5-flash"
MONGO_URI = os.environ.get("MONGO_URI", "").strip()
TOKEN_PAYMENT = os.environ.get("TOKEN_PAYMENT", "").strip()

# --- ADMIN ---
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

def is_admin(user_id):
    return user_id == ADMIN_ID

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# --- BANCO ---
client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
pacientes_coll = db['pacientes']
uso_coll = db['uso_usuarios']

# --- MEMÓRIA CLÍNICA INTELIGENTE ---
def montar_memoria_clinica(paciente):
    memoria = ""

    if paciente.get("ultima_analise"):
        memoria += f"\nÚltima análise:\n{paciente['ultima_analise'][:800]}"

    if paciente.get("evolucao"):
        memoria += f"\nEvolução:\n{paciente['evolucao'][-800:]}"

    if paciente.get("registros_clinicos"):
        memoria += "\nRegistros adicionais:\n"
        for r in paciente["registros_clinicos"][-5:]:
            memoria += f"- ({r['data']}) {r['info']}\n"

    return memoria.strip()

# --- CONTROLE DE USO ---
LIMITE_GRATUITO = 5

def pode_usar(user_id):
    if is_admin(user_id):
        return True

    user = uso_coll.find_one({"user_id": user_id})

    if not user:
        uso_coll.insert_one({"user_id": user_id, "uso": 1})
        return True

    if user["uso"] >= LIMITE_GRATUITO:
        return False

    uso_coll.update_one({"user_id": user_id}, {"$inc": {"uso": 1}})
    return True

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
        types.InlineKeyboardButton("📂 Histórico de Pacientes", callback_data="ver_historico"),
        types.InlineKeyboardButton("📝 Atualizar Prontuário", callback_data="atualizar_prontuario"),
        types.InlineKeyboardButton("➕ Adicionar Informação Clínica", callback_data="add_info"),
        types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica"),
        types.InlineKeyboardButton("💎 Planos de Acesso Pro", callback_data="planos")
    )
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(
        message.chat.id,
        "🚀 **MestreFisio V5.0 Especialista**\nAgora com memória clínica inteligente.",
        reply_markup=menu_principal()
    )

# --- CALLBACK ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)

    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)

    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual condição deseja analisar hoje?")
        bot.register_next_step_handler(msg, processar_ia_direta)

    elif call.data == "ver_historico":
        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))
        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Histórico vazio.")
        else:
            txt = "📂 **Seus Pacientes:**\n" + "\n".join([f"• {p['nome']} ({p['data']})" for p in pacientes])
            bot.send_message(call.message.chat.id, txt)

    elif call.data == "atualizar_prontuario":
        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))

        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Nenhum paciente cadastrado.")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)

        for p in pacientes:
            markup.add(types.InlineKeyboardButton(
                f"{p['nome']}",
                callback_data=f"editar_{p['nome']}"
            ))

        bot.send_message(call.message.chat.id, "📝 Selecione o paciente:", reply_markup=markup)

    elif call.data.startswith("editar_"):
        nome = call.data.replace("editar_", "")

        paciente = pacientes_coll.find_one({
            "profissional_id": call.from_user.id,
            "nome": nome
        })

        resumo = paciente.get("evolucao", "Sem evolução registrada ainda.")
        ultima = paciente.get("ultima_analise", "Sem análise prévia.")

        texto = f"📂 **{nome}**\n\n🧠 Última análise:\n{ultima[:500]}...\n\n📈 Evolução:\n{resumo}"

        msg = bot.send_message(call.message.chat.id, texto + "\n\n✍️ Envie nova evolução:")
        bot.register_next_step_handler(msg, salvar_evolucao, nome)

    elif call.data == "add_info":

        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))

        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Nenhum paciente cadastrado.")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)

        for p in pacientes:
            markup.add(types.InlineKeyboardButton(
                f"{p['nome']}",
                callback_data=f"addinfo_{p['nome']}"
            ))

        bot.send_message(call.message.chat.id, "➕ Selecione o paciente:", reply_markup=markup)

    elif call.data.startswith("addinfo_"):
        nome = call.data.replace("addinfo_", "")

        msg = bot.send_message(
            call.message.chat.id,
            f"🧠 Envie a nova informação clínica para {nome}:"
        )

        bot.register_next_step_handler(msg, adicionar_info_clinica, nome)

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

# --- FLUXO PACIENTE ---
def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: **{nome}**\nDescreva o quadro clínico:")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):

    paciente = pacientes_coll.find_one({
        "profissional_id": message.from_user.id,
        "nome": nome
    }) or {}

    memoria = montar_memoria_clinica(paciente)

    prompt = f"""
{PROMPT_SISTEMA}

Paciente: {nome}

Histórico clínico:
{memoria}

Nova informação:
{message.text}

Atualize o raciocínio considerando toda evolução.
"""

    chamar_gemini(message, prompt, nome)

def processar_ia_direta(message):
    prompt = f"{PROMPT_SISTEMA}\n\n{message.text}"
    chamar_gemini(message, prompt)

# --- EVOLUÇÃO ---
def salvar_evolucao(message, nome):
    nova_info = message.text

    paciente = pacientes_coll.find_one({
        "profissional_id": message.from_user.id,
        "nome": nome
    })

    evolucao_antiga = paciente.get("evolucao", "")

    nova_evolucao = evolucao_antiga + f"\n\n[{time.strftime('%d/%m/%Y')}]\n{nova_info}"

    pacientes_coll.update_one(
        {"profissional_id": message.from_user.id, "nome": nome},
        {"$set": {"evolucao": nova_evolucao}},
        upsert=True
    )

    bot.send_message(message.chat.id, "✅ Evolução salva!", reply_markup=menu_principal())

# --- NOVA INFO CLÍNICA ---
def adicionar_info_clinica(message, nome):

    pacientes_coll.update_one(
        {"profissional_id": message.from_user.id, "nome": nome},
        {
            "$push": {
                "registros_clinicos": {
                    "data": time.strftime("%d/%m/%Y"),
                    "info": message.text
                }
            }
        },
        upsert=True
    )

    bot.send_message(message.chat.id, "✅ Informação adicionada!", reply_markup=menu_principal())

# --- IA ---
def chamar_gemini(message, prompt, nome_paciente=None):

    if not pode_usar(message.from_user.id):
        bot.send_message(message.chat.id, "🚫 Limite atingido.")
        return

    aguarde = bot.send_message(message.chat.id, "🧠 Processando...")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"

    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=400)
        res_data = response.json()

        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']

            if nome_paciente:
                pacientes_coll.update_one(
                    {"profissional_id": message.from_user.id, "nome": nome_paciente},
                    {"$set": {"ultima_analise": analise, "data": time.strftime("%d/%m/%Y")}},
                    upsert=True
                )

            bot.delete_message(message.chat.id, aguarde.message_id)

            for p in [analise[i:i+1500] for i in range(0, len(analise), 1500)]:
                bot.send_message(message.chat.id, p)
                time.sleep(1)

            bot.send_message(message.chat.id, "✅ Finalizado.", reply_markup=menu_principal())

    except Exception as e:
        print(e)
        bot.send_message(message.chat.id, "❌ Erro na IA.")

# --- EXECUÇÃO ---
if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    time.sleep(2)
    bot.infinity_polling(timeout=120, long_polling_timeout=60)
