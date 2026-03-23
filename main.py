import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V7.1 - Estável"

@app.route('/pacientes/<user_id>')
def listar_pacientes(user_id):
    pacientes = list(pacientes_coll.find({"profissional_id": int(user_id)}))
    return {"pacientes": [
        {"nome": p["nome"], "evolucoes": len(p.get("evolucoes", []))}
        for p in pacientes
    ]}

def run():
    app.run(host='0.0.0.0', port=10000)

# --- CONFIG ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "").strip()
API_KEY_IA = os.environ.get("API_KEY_IA", "").strip()
MODELO = "gemini-2.5-flash"
MONGO_URI = os.environ.get("MONGO_URI", "").strip()
TOKEN_PAYMENT = os.environ.get("TOKEN_PAYMENT", "").strip()

# ADMIN seguro (não quebra se vazio)
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# --- BANCO ---
client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
pacientes_coll = db['pacientes']
usuarios_coll = db['usuarios']

# --- PDF ---
def gerar_pdf_paciente(chat_id, paciente):
    nome_arquivo = f"/mnt/data/{paciente['nome']}.pdf"
    doc = SimpleDocTemplate(nome_arquivo)
    styles = getSampleStyleSheet()
    conteudo = []

    conteudo.append(Paragraph(f"Prontuário - {paciente['nome']}", styles['Title']))
    conteudo.append(Spacer(1, 12))

    for evo in paciente.get("evolucoes", []):
        conteudo.append(Paragraph(
            f"{evo['data']}<br/>{evo['relato']}<br/>{evo['analise']}",
            styles['Normal']
        ))
        conteudo.append(Spacer(1, 10))

    doc.build(conteudo)

    with open(nome_arquivo, "rb") as f:
        bot.send_document(chat_id, f)

# --- RESUMO ---
def gerar_resumo(paciente):
    textos = "\n".join([e["relato"] for e in paciente.get("evolucoes", [])])
    if not textos:
        return "Sem dados."

    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}",
        json={"contents": [{"parts": [{"text": f"Resuma clinicamente:\n{textos}"}]}]}
    )

    try:
        return response.json()['candidates'][0]['content']['parts'][0]['text']
    except:
        return "Erro resumo"

# --- MÉTRICAS ---
def obter_metricas():
    total_usuarios = usuarios_coll.count_documents({})
    total_pacientes = pacientes_coll.count_documents({})
    pro_users = usuarios_coll.count_documents({"plano": "PRO"})

    return f"""
📊 MÉTRICAS

👥 Usuários: {total_usuarios}
💎 PRO: {pro_users}
🧠 Pacientes: {total_pacientes}
"""

# --- USUÁRIOS PESADOS ---
def usuarios_pesados():
    users = usuarios_coll.find({"consultas": {"$gt": 50}})
    lista = [f"{u['user_id']} → {u.get('consultas',0)}" for u in users]
    return "🚨 Alto uso:\n\n" + "\n".join(lista) if lista else "Nenhum abuso detectado."

# --- MENU ---
def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👤 Novo Paciente", callback_data="novo_paciente"),
        types.InlineKeyboardButton("🧠 Atualizar", callback_data="atualizar_paciente"),
        types.InlineKeyboardButton("📂 Histórico", callback_data="ver_historico"),
        types.InlineKeyboardButton("📄 PDF", callback_data="gerar_pdf"),
        types.InlineKeyboardButton("📊 Resumo", callback_data="resumo"),
        types.InlineKeyboardButton("💎 PRO", callback_data="planos"),
        types.InlineKeyboardButton("⚙️ Admin", callback_data="admin")
    )
    return markup

# --- START ---
@bot.message_handler(commands=['start'])
def start(message):
    if not usuarios_coll.find_one({"user_id": message.from_user.id}):
        usuarios_coll.insert_one({
            "user_id": message.from_user.id,
            "plano": "FREE",
            "consultas": 0
        })

        for admin in ADMIN_IDS:
            bot.send_message(admin, f"🚀 Novo usuário: {message.from_user.id}")

    bot.send_message(message.chat.id, "MestreFisio V7.1", reply_markup=menu_principal())

# --- CALLBACK ---
@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    bot.answer_callback_query(call.id)

    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "Nome:")
        bot.register_next_step_handler(msg, obter_nome)

    elif call.data == "atualizar_paciente":
        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))
        markup = types.InlineKeyboardMarkup()
        for p in pacientes:
            markup.add(types.InlineKeyboardButton(p['nome'], callback_data=f"pac_{p['nome']}"))
        bot.send_message(call.message.chat.id, "Selecione:", reply_markup=markup)

    elif call.data.startswith("pac_"):
        nome = call.data.replace("pac_", "")
        msg = bot.send_message(call.message.chat.id, f"Atualizar {nome}:")
        bot.register_next_step_handler(msg, lambda m: processar(m, nome))

    elif call.data == "ver_historico":
        pacientes = pacientes_coll.find({"profissional_id": call.from_user.id})
        for p in pacientes:
            bot.send_message(call.message.chat.id, f"{p['nome']} ({len(p.get('evolucoes', []))})")

    elif call.data == "gerar_pdf":
        pacientes = pacientes_coll.find({"profissional_id": call.from_user.id})
        markup = types.InlineKeyboardMarkup()
        for p in pacientes:
            markup.add(types.InlineKeyboardButton(p['nome'], callback_data=f"pdf_{p['nome']}"))
        bot.send_message(call.message.chat.id, "Selecione:", reply_markup=markup)

    elif call.data.startswith("pdf_"):
        nome = call.data.replace("pdf_", "")
        paciente = pacientes_coll.find_one({"profissional_id": call.from_user.id, "nome": nome})
        gerar_pdf_paciente(call.message.chat.id, paciente)

    elif call.data == "resumo":
        pacientes = pacientes_coll.find({"profissional_id": call.from_user.id})
        markup = types.InlineKeyboardMarkup()
        for p in pacientes:
            markup.add(types.InlineKeyboardButton(p['nome'], callback_data=f"res_{p['nome']}"))
        bot.send_message(call.message.chat.id, "Selecione:", reply_markup=markup)

    elif call.data.startswith("res_"):
        nome = call.data.replace("res_", "")
        paciente = pacientes_coll.find_one({"profissional_id": call.from_user.id, "nome": nome})
        bot.send_message(call.message.chat.id, gerar_resumo(paciente))

    elif call.data == "planos":
        bot.send_invoice(
            chat_id=call.message.chat.id,
            title="PRO",
            description="Acesso ilimitado",
            provider_token=TOKEN_PAYMENT,
            currency="BRL",
            prices=[types.LabeledPrice("Plano PRO", 5990)],
            invoice_payload="pro"
        )

    # --- ADMIN ---
    elif call.data == "admin":
        if call.from_user.id not in ADMIN_IDS:
            return

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("📊 Métricas", callback_data="adm_m"),
            types.InlineKeyboardButton("🚨 Uso alto", callback_data="adm_u"),
            types.InlineKeyboardButton("👥 Usuários", callback_data="adm_l")
        )
        bot.send_message(call.message.chat.id, "Admin:", reply_markup=markup)

    elif call.data == "adm_m":
        if call.from_user.id in ADMIN_IDS:
            bot.send_message(call.message.chat.id, obter_metricas())

    elif call.data == "adm_u":
        if call.from_user.id in ADMIN_IDS:
            bot.send_message(call.message.chat.id, usuarios_pesados())

    elif call.data == "adm_l":
        if call.from_user.id in ADMIN_IDS:
            users = usuarios_coll.find().limit(20)
            texto = "\n".join([f"{u['user_id']} | {u.get('plano','FREE')}" for u in users])
            bot.send_message(call.message.chat.id, texto)

# --- PAGAMENTO ---
@bot.pre_checkout_query_handler(func=lambda q: True)
def checkout(q):
    bot.answer_pre_checkout_query(q.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def pagamento(message):
    usuarios_coll.update_one(
        {"user_id": message.from_user.id},
        {"$set": {"plano": "PRO", "consultas": 0}},
        upsert=True
    )
    bot.send_message(message.chat.id, "💎 PRO ativo")

# --- IA ---
def processar(message, nome=None):
    user_id = message.from_user.id
    user = usuarios_coll.find_one({"user_id": user_id}) or {"plano": "FREE", "consultas": 0}

    if user_id not in ADMIN_IDS:
        if user["plano"] != "PRO" and user["consultas"] >= 3:
            bot.send_message(message.chat.id, "Limite FREE atingido.")
            return

    bot.send_message(message.chat.id, "Processando...")

    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}",
        json={"contents": [{"parts": [{"text": message.text}]}]}
    )

    try:
        resposta = response.json()['candidates'][0]['content']['parts'][0]['text']
    except:
        resposta = "Erro IA"

    if nome:
        pacientes_coll.update_one(
            {"profissional_id": user_id, "nome": nome},
            {"$push": {"evolucoes": {
                "data": time.strftime("%d/%m/%Y"),
                "relato": message.text,
                "analise": resposta
            }}},
            upsert=True
        )

    usuarios_coll.update_one(
        {"user_id": user_id},
        {"$inc": {"consultas": 1}},
        upsert=True
    )

    # ALERTA ADMIN
    if user.get("consultas", 0) > 50:
        for admin in ADMIN_IDS:
            bot.send_message(admin, f"🚨 Usuário {user_id} alto uso")

    bot.send_message(message.chat.id, resposta)

def obter_nome(message):
    nome = message.text.upper()
    msg = bot.send_message(message.chat.id, f"{nome} - descreva:")
    bot.register_next_step_handler(msg, lambda m: processar(m, nome))

# --- EXEC ---
if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling(skip_pending=True)
