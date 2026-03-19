import telebot, requests, os, time, pymongo
from telebot import types
from flask import Flask
from threading import Thread
from datetime import datetime
from fpdf import FPDF

# --- 1. CONFIGURAÇÕES INICIAIS ---
MONGO_URI = os.environ.get("MONGO_URI")
client = pymongo.MongoClient(MONGO_URI)
db = client["MestreFisioDB"]
pacientes_coll = db["pacientes"]
usuarios_coll = db["usuarios"]

ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-2.0-flash" # Versão estável
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# --- 2. SERVIDOR WEB (ANTI-SONO) ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V6.1 Ativo"

def run(): app.run(host='0.0.0.0', port=10000)

# --- 3. CLASSE DO PDF PROFISSIONAL ---
class PDF_Relatorio(FPDF):
    def __init__(self, nome_prof, registro_prof):
        super().__init__()
        self.nome_prof = nome_prof
        self.registro_prof = registro_prof

    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'MESTREFISIO - INTELIGÊNCIA CLÍNICA', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.line(10, 282, 200, 282)
        self.cell(0, 10, f'Documento gerado por {self.nome_prof} | {self.registro_prof}', 0, 0, 'C')

# --- 4. FUNÇÕES DE APOIO (LÓGICA) ---
def verificar_registro(user_id, chat_id):
    perfil = usuarios_coll.find_one({"user_id": user_id})
    if not perfil:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✍️ Configurar Perfil", callback_data="config_perfil"))
        bot.send_message(chat_id, "⚠️ **Acesso Restrito.**\nCadastre seu nome e CREFITO para liberar o uso.", reply_markup=markup)
        return False, None
    return True, perfil

def verificar_limite(user_id, perfil):
    if user_id == ADMIN_ID: return True, 0
    uso = perfil.get("laudos_usados", 0)
    if uso >= 3: return False, uso
    return True, uso

def alertar_admin(nome, registro):
    if ADMIN_ID:
        bot.send_message(ADMIN_ID, f"🆕 **NOVO USUÁRIO:**\n{nome}\n{registro}")

# --- 5. INTERFACE (MENUS) ---
def menu_principal(user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👤 Novo Paciente / Laudo PhD", callback_data="novo_paciente"),
        types.InlineKeyboardButton("💡 Consulta Técnica Avulsa", callback_data="consulta_avulsa"),
        types.InlineKeyboardButton("📋 Meus Pacientes", callback_data="listar_pacientes"),
        types.InlineKeyboardButton("⚙️ Configurar Meu Perfil", callback_data="config_perfil")
    )
    if user_id == ADMIN_ID:
        markup.add(types.InlineKeyboardButton("📊 Painel Administrativo", callback_data="painel_admin"))
    return markup

# --- 6. COMANDOS E CALLBACKS ---
@bot.message_handler(commands=['start'])
def welcome(message):
    bot.send_message(message.chat.id, "🚀 **MestreFisio V6.1**\nSeu assistente PhD em Fisioterapia.", reply_markup=menu_principal(message.from_user.id))

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    
    if call.data == "config_perfil":
        msg = bot.send_message(call.message.chat.id, "✍️ Digite: **Seu Nome - Registro**")
        bot.register_next_step_handler(msg, processar_perfil)
    
    elif call.data == "novo_paciente":
        ok, perfil = verificar_registro(user_id, call.message.chat.id)
        if ok:
            pode_usar, qtd = verificar_limite(user_id, perfil)
            if pode_usar:
                msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
                bot.register_next_step_handler(msg, iniciar_laudo)
            else:
                bot.send_message(call.message.chat.id, "🚫 Limite de 3 laudos atingido.")

    elif call.data == "consulta_avulsa":
        ok, _ = verificar_registro(user_id, call.message.chat.id)
        if ok:
            msg = bot.send_message(call.message.chat.id, "💡 Qual sua dúvida técnica?")
            bot.register_next_step_handler(msg, processar_consulta)

    elif call.data == "listar_pacientes":
        cursor = pacientes_coll.find({"user_id": user_id}, {"nome": 1})
        lista = [p["nome"] for p in cursor]
        bot.send_message(call.message.chat.id, f"📂 **Seus Pacientes:**\n\n" + "\n".join(lista) if lista else "Vazio.")

    elif call.data == "painel_admin":
        if user_id == ADMIN_ID:
            u = usuarios_coll.count_documents({})
            p = pacientes_coll.count_documents({})
            bot.send_message(call.message.chat.id, f"📊 **ADMIN:**\nProfissionais: {u}\nLaudos: {p}")

# --- 7. PROCESSAMENTO (IA E PDF) ---
def processar_perfil(message):
    try:
        nome, reg = message.text.split("-")
        usuarios_coll.update_one({"user_id": message.from_user.id}, {"$set": {"nome": nome.strip(), "registro": reg.strip()}}, upsert=True)
        alertar_admin(nome, reg)
        bot.send_message(message.chat.id, "✅ Perfil salvo!", reply_markup=menu_principal(message.from_user.id))
    except:
        bot.send_message(message.chat.id, "❌ Use o formato: Nome - Registro")

def iniciar_laudo(message):
    nome_p = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: {nome_p}\nDescreva o caso:")
    bot.register_next_step_handler(msg, gerar_laudo_phd, nome_p)

def gerar_laudo_phd(message, nome_p):
    user_id = message.from_user.id
    aguarde = bot.send_message(message.chat.id, "🧠 Gerando Relatório...")
    perfil = usuarios_coll.find_one({"user_id": user_id})
    
    prompt = f"Fisioterapeuta PhD. Relatório de 15 tópicos para o paciente {nome_p}: {message.text}"
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]})
        analise = res.json()['candidates'][0]['content']['parts'][0]['text']
        
        # Incrementar uso e Salvar no Banco
        usuarios_coll.update_one({"user_id": user_id}, {"$inc": {"laudos_usados": 1}})
        pacientes_coll.update_one({"user_id": user_id, "nome": nome_p}, {"$push": {"consultas": {"data": datetime.now(), "txt": analise}}}, upsert=True)
        
        # PDF
        path = f"Laudo_{nome_p}.pdf"
        pdf = PDF_Relatorio(perfil['nome'], perfil['registro'])
        pdf.add_page()
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(0, 10, f"Paciente: {nome_p}", 0, 1)
        pdf.set_font("Arial", size=11)
        pdf.multi_cell(0, 8, analise.encode('latin-1', 'replace').decode('latin-1'))
        pdf.output(path)
        
        bot.delete_message(message.chat.id, aguarde.message_id)
        with open(path, "rb") as f: bot.send_document(message.chat.id, f)
        os.remove(path)
    except:
        bot.send_message(message.chat.id, "❌ Erro ao gerar laudo.")

def processar_consulta(message):
    aguarde = bot.send_message(message.chat.id, "🧠 Consultando...")
    prompt = f"Fisioterapeuta PhD. Responda tecnicamente: {message.text}"
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]})
        bot.send_message(message.chat.id, res.json()['candidates'][0]['content']['parts'][0]['text'])
    except:
        bot.send_message(message.chat.id, "❌ Erro na consulta.")

if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling()
