import telebot, requests, os, time
from telebot import types

TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = telebot.TeleBot(TOKEN)

usuarios = {}
historico_pacientes = {}

PROMPT_SISTEMA = """
Você é um especialista clínico em fisioterapia, com base em:
- Kapandji
- Cadeias musculares (Busquet)
- PNF (Kabat)
- RPG
- McKenzie
- Osteopatia
- Medicina Germânica

Responda com:
- Análise clínica profunda
- Hipóteses
- Relações musculares
- Sugestões de tratamento
"""

# ==============================
# MENU PRINCIPAL
# ==============================

def menu_principal(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🧠 Dúvida Técnica")
    markup.add("👤 Novo Paciente", "📋 Ver Pacientes")
    markup.add("➕ Adicionar Informação Clínica")

    if chat_id == ADMIN_ID:
        markup.add("📊 Métricas")

    bot.send_message(chat_id, "Escolha uma opção:", reply_markup=markup)

# ==============================
# START
# ==============================

@bot.message_handler(commands=['start'])
def start(message):
    usuarios[message.chat.id] = {"modo": None}
    bot.send_message(message.chat.id, "Sistema iniciado.")
    menu_principal(message.chat.id)

# ==============================
# PROCESSAR IA DIRETA (CORRIGIDO)
# ==============================

def processar_ia_direta(message):
    prompt = f"{PROMPT_SISTEMA}\n\nExplique detalhadamente:\n{message.text}"
    chamar_gemini(message, prompt)

# ==============================
# CHAMADA DA IA (ROBUSTA)
# ==============================

def chamar_gemini(message, prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_KEY}"

    headers = {"Content-Type": "application/json"}

    data = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }

    msg = bot.send_message(message.chat.id, "⏳ Processando...")

    print("\n===== PROMPT ENVIADO =====\n", prompt[:500])

    try:
        response = requests.post(url, headers=headers, json=data)
        res_data = response.json()

        print("\n===== RESPOSTA IA =====\n", res_data)

        try:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
        except:
            bot.delete_message(message.chat.id, msg.message_id)
            bot.send_message(message.chat.id, "⚠️ Erro ao interpretar resposta da IA.")
            print("Erro de parsing:", res_data)
            return

        partes = [analise[i:i+4000] for i in range(0, len(analise), 4000)]

        bot.delete_message(message.chat.id, msg.message_id)

        for p in partes:
            bot.send_message(message.chat.id, p)

    except Exception as e:
        bot.delete_message(message.chat.id, msg.message_id)
        bot.send_message(message.chat.id, f"Erro: {e}")
        print("Erro geral:", e)

# ==============================
# PACIENTES
# ==============================

@bot.message_handler(func=lambda m: m.text == "👤 Novo Paciente")
def novo_paciente(message):
    usuarios[message.chat.id]["modo"] = "novo_paciente"
    bot.send_message(message.chat.id, "Digite o nome do paciente:")

@bot.message_handler(func=lambda m: m.text == "📋 Ver Pacientes")
def ver_pacientes(message):
    if not historico_pacientes:
        bot.send_message(message.chat.id, "Nenhum paciente cadastrado.")
        return

    nomes = "\n".join(historico_pacientes.keys())
    bot.send_message(message.chat.id, f"Pacientes:\n{nomes}")

@bot.message_handler(func=lambda m: m.text == "➕ Adicionar Informação Clínica")
def adicionar_info(message):
    usuarios[message.chat.id]["modo"] = "add_info"
    bot.send_message(message.chat.id, "Digite o nome do paciente:")

# ==============================
# MÉTRICAS ADMIN
# ==============================

@bot.message_handler(func=lambda m: m.text == "📊 Métricas")
def metricas(message):
    if message.chat.id != ADMIN_ID:
        return

    total = len(usuarios)
    pacientes = len(historico_pacientes)

    bot.send_message(message.chat.id,
        f"👥 Usuários: {total}\n🧾 Pacientes: {pacientes}"
    )

# ==============================
# HANDLER PRINCIPAL
# ==============================

@bot.message_handler(func=lambda message: True)
def handler(message):
    chat_id = message.chat.id

    if chat_id not in usuarios:
        usuarios[chat_id] = {"modo": None}

    modo = usuarios[chat_id]["modo"]

    # =====================
    # DÚVIDA TÉCNICA
    # =====================
    if message.text == "🧠 Dúvida Técnica":
        usuarios[chat_id]["modo"] = "ia_direta"
        bot.send_message(chat_id, "Digite sua dúvida:")
        return

    if modo == "ia_direta":
        processar_ia_direta(message)
        return

    # =====================
    # NOVO PACIENTE
    # =====================
    if modo == "novo_paciente":
        historico_pacientes[message.text] = []
        usuarios[chat_id]["modo"] = None
        bot.send_message(chat_id, "Paciente cadastrado.")
        return

    # =====================
    # ADICIONAR INFO
    # =====================
    if modo == "add_info":
        usuarios[chat_id]["paciente_temp"] = message.text
        usuarios[chat_id]["modo"] = "salvar_info"
        bot.send_message(chat_id, "Digite a informação clínica:")
        return

    if modo == "salvar_info":
        nome = usuarios[chat_id].get("paciente_temp")

        if nome not in historico_pacientes:
            bot.send_message(chat_id, "Paciente não encontrado.")
        else:
            historico_pacientes[nome].append(message.text)
            bot.send_message(chat_id, "Informação adicionada.")

        usuarios[chat_id]["modo"] = None
        return

# ==============================
# LOOP
# ==============================

print("BOT RODANDO...")
bot.infinity_polling()
