import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V6.0 - Hospital Premium Ativo 🏥🧠"

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

# --- MEMÓRIA CLÍNICA ---
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

# --- LINHA DO TEMPO ---
def gerar_linha_do_tempo(paciente):
    timeline = ""
    if paciente.get("registros_clinicos"):
        for r in paciente["registros_clinicos"]:
            timeline += f"{r['data']} → {r['info']}\n"
    return timeline if timeline else "Sem registros ainda."

# --- RED FLAGS + SCORE ---
def analisar_risco_clinico(texto):

    palavras_redflag = [
        "perda de força", "incontinência", "anestesia em sela",
        "dor noturna intensa", "febre", "histórico de câncer",
        "trauma recente", "déficit neurológico", "paralisia"
    ]

    score = 0
    alertas = []
    texto_lower = texto.lower()

    for palavra in palavras_redflag:
        if palavra in texto_lower:
            score += 2
            alertas.append(palavra)

    return min(score, 10), alertas

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
Atue como um Fisioterapeuta PhD e especialista clínico hospitalar.

Forneça análise em 15 tópicos obrigatórios:
Definição, Anatomia/Biomecânica, Etiologia, Sintomas, Raciocínio, Avaliação, Testes, Diagnóstico Diferencial, Exames, Classificação, Conduta, Protocolo Atleta, Algoritmo, Red Flags e Evidências.

Inclua também:
- Nível de gravidade (0–10)
- Conduta recomendada
- Necessidade de encaminhamento

Use linguagem científica de alto nível.
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
        types.InlineKeyboardButton("💎 Planos Pro", callback_data="planos")
    )
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "🏥 MestreFisio V6 Hospital Premium", reply_markup=menu_principal())

# --- CALLBACK ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)

    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "Nome do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)

    elif call.data == "add_info":
        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))
        markup = types.InlineKeyboardMarkup()
        for p in pacientes:
            markup.add(types.InlineKeyboardButton(p['nome'], callback_data=f"addinfo_{p['nome']}"))
        bot.send_message(call.message.chat.id, "Selecione paciente:", reply_markup=markup)

    elif call.data.startswith("addinfo_"):
        nome = call.data.replace("addinfo_", "")
        msg = bot.send_message(call.message.chat.id, "Nova info clínica:")
        bot.register_next_step_handler(msg, adicionar_info_clinica, nome)

    elif call.data.startswith("editar_"):
        nome = call.data.replace("editar_", "")

        paciente = pacientes_coll.find_one({
            "profissional_id": call.from_user.id,
            "nome": nome
        })

        score = paciente.get("score_risco", 0)
        alertas = paciente.get("alertas", [])

        texto = f"""📂 {nome}

Score: {score}/10
Alertas: {alertas}

Última análise:
{paciente.get("ultima_analise","")[:500]}
"""

        msg = bot.send_message(call.message.chat.id, texto + "\nNova evolução:")
        bot.register_next_step_handler(msg, salvar_evolucao, nome)

# --- PACIENTE ---
def obter_nome_paciente(message):
    nome = message.text.upper()
    msg = bot.send_message(message.chat.id, "Descreva o caso:")
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

Histórico:
{memoria}

Nova informação:
{message.text}
"""

    chamar_gemini(message, prompt, nome)

# --- SALVAR INFO ---
def adicionar_info_clinica(message, nome):
    pacientes_coll.update_one(
        {"profissional_id": message.from_user.id, "nome": nome},
        {"$push": {"registros_clinicos": {"data": time.strftime("%d/%m/%Y"), "info": message.text}}},
        upsert=True
    )
    bot.send_message(message.chat.id, "Info salva", reply_markup=menu_principal())

def salvar_evolucao(message, nome):
    pacientes_coll.update_one(
        {"profissional_id": message.from_user.id, "nome": nome},
        {"$set": {"evolucao": message.text}},
        upsert=True
    )
    bot.send_message(message.chat.id, "Evolução salva", reply_markup=menu_principal())

# --- IA ---
def chamar_gemini(message, prompt, nome_paciente=None):

    if not pode_usar(message.from_user.id):
        bot.send_message(message.chat.id, "Limite atingido")
        return

    aguarde = bot.send_message(message.chat.id, "Processando...")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"

    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=400)
        res_data = response.json()

        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']

            score, alertas = analisar_risco_clinico(prompt)

            if nome_paciente:
                pacientes_coll.update_one(
                    {"profissional_id": message.from_user.id, "nome": nome_paciente},
                    {
                        "$set": {
                            "ultima_analise": analise,
                            "data": time.strftime("%d/%m/%Y"),
                            "score_risco": score,
                            "alertas": alertas
                        }
                    },
                    upsert=True
                )

                if score >= 6:
                    try:
                        bot.send_message(ADMIN_ID, f"🚨 ALERTA {nome_paciente} Score {score}")
                    except:
                        pass

            bot.delete_message(message.chat.id, aguarde.message_id)

            for p in [analise[i:i+1500] for i in range(0, len(analise), 1500)]:
                bot.send_message(message.chat.id, p)

            bot.send_message(message.chat.id, "Finalizado", reply_markup=menu_principal())

    except Exception as e:
        print(e)
        bot.send_message(message.chat.id, "Erro IA")

# --- EXEC ---
if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    time.sleep(2)
    bot.infinity_polling()
