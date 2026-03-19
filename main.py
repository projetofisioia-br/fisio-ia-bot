import telebot, requests, os, time, pymongo
from telebot import types
from flask import Flask
from threading import Thread
from datetime import datetime
from fpdf import FPDF

# --- 1. CONFIGURAÇÃO DO BANCO E ADMIN ---
MONGO_URI = os.environ.get("MONGO_URI")
client = pymongo.MongoClient(MONGO_URI)
db = client["MestreFisioDB"]
pacientes_coll = db["pacientes"]
usuarios_coll = db["usuarios"]

# Captura o ID do Admin (você) configurado no Render
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))

# --- 2. SERVIDOR WEB (KEEP ALIVE) ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V5.4 - Segurança e SaaS Ativo"

def run(): app.run(host='0.0.0.0', port=10000)

# --- 3. CONFIGURAÇÕES DO BOT ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-2.5-flash"
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# --- 4. CLASSE DE PDF DINÂMICO ---
class PDF_Relatorio(FPDF):
    def __init__(self, nome_prof, registro_prof):
        super().__init__()
        self.nome_prof = nome_prof
        self.registro_prof = registro_prof

    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'MESTREFISIO - RELATÓRIO TÉCNICO PhD', 0, 1, 'C')
        self.set_font('Arial', '', 10)
        self.cell(0, 5, f'Profissional: {self.nome_prof}', 0, 1, 'C')
        self.ln(10)
        self.line(10, 30, 200, 30)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.line(10, 282, 200, 282)
        self.cell(0, 10, f'{self.nome_prof} | {self.registro_prof} | Página ' + str(self.page_no()), 0, 0, 'C')

# --- 5. FUNÇÕES DE SEGURANÇA E APOIO ---
def verificar_registro(message):
    """Verifica se o usuário já cadastrou o perfil no banco"""
    user_id = message.from_user.id
    perfil = usuarios_coll.find_one({"user_id": user_id})
    if not perfil:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✍️ Cadastrar Meu Perfil Agora", callback_data="config_perfil"))
        bot.send_message(message.chat.id, 
            "⚠️ **ACESSO RESTRITO**\n\nPara gerar laudos técnicos e usar a IA, você precisa configurar seu perfil (Nome e CREFITO) primeiro.", 
            reply_markup=markup)
        return False
    return True

def obter_perfil(user_id):
    perfil = usuarios_coll.find_one({"user_id": user_id})
    if perfil: return perfil['nome'], perfil['registro']
    return "Fisioterapeuta", "Registro não cadastrado"

def gerar_pdf(nome_paciente, texto_laudo, nome_prof, registro_prof):
    pdf = PDF_Relatorio(nome_prof, registro_prof)
    pdf.add_page()
    pdf.set_font("Arial", size=11)
    texto_limpo = texto_laudo.encode('latin-1', 'replace').decode('latin-1')
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"Paciente: {nome_paciente}", 0, 1)
    pdf.ln(5)
    pdf.set_font("Arial", size=11)
    pdf.multi_cell(0, 7, texto_limpo)
    path = f"Laudo_{nome_paciente.replace(' ', '_')}.pdf"
    pdf.output(path)
    return path

# --- 6. INTERFACE E COMANDOS ---
def menu_principal(user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👤 Novo Paciente / Analisar", callback_data="novo_paciente"),
        types.InlineKeyboardButton("📋 Meus Pacientes", callback_data="listar_pacientes"),
        types.InlineKeyboardButton("⚙️ Configurar Meu Perfil", callback_data="config_perfil")
    )
    # Botão especial apenas para você (Admin)
    if user_id == ADMIN_ID:
        markup.add(types.InlineKeyboardButton("📊 Painel Administrativo", callback_data="painel_admin"))
    return markup

@bot.message_handler(commands=['start'])
def welcome(message):
    bot.send_message(message.chat.id, "🚀 **MestreFisio V5.4**\nGestão Clínica e IA PhD.", reply_markup=menu_principal(message.from_user.id))

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    
    if call.data == "config_perfil":
        msg = bot.send_message(call.message.chat.id, "✍️ Digite seu Nome e Registro no formato:\n**Nome Sobrenome - CREFITO 0000**")
        bot.register_next_step_handler(msg, processar_perfil)
    
    elif call.data == "novo_paciente":
        # TRAVA ATIVA: Só inicia se tiver perfil
        if verificar_registro(call):
            msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
            bot.register_next_step_handler(msg, iniciar_fluxo_paciente)

    elif call.data == "painel_admin":
        if user_id == ADMIN_ID:
            u_count = usuarios_coll.count_documents({})
            p_count = pacientes_coll.count_documents({})
            bot.send_message(call.message.chat.id, f"📊 **ESTATÍSTICAS DO SISTEMA**\n\n👥 Profissionais: {u_count}\n📄 Laudos Totais: {p_count}")

# --- 7. LÓGICA DE PROCESSAMENTO ---
def processar_perfil(message):
    try:
        partes = message.text.split("-")
        nome, registro = partes[0].strip(), partes[1].strip()
        usuarios_coll.update_one({"user_id": message.from_user.id}, {"$set": {"nome": nome, "registro": registro}}, upsert=True)
        bot.send_message(message.chat.id, "✅ Perfil salvo com sucesso!", reply_markup=menu_principal(message.from_user.id))
    except:
        bot.send_message(message.chat.id, "❌ Erro. Use o formato: Nome - Registro")

def iniciar_fluxo_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: **{nome}**\nDescreva o caso clínico:")
    bot.register_next_step_handler(msg, processar_ia, nome)

def processar_ia(message, nome):
    user_id = message.from_user.id
    aguarde = bot.send_message(message.chat.id, "🧠 **Gerando Relatório PhD...**")
    nome_prof, reg_prof = obter_perfil(user_id)
    
    prompt = f"Fisioterapeuta PhD. Analise 15 tópicos: Paciente {nome}. {message.text}"
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=300)
        analise = res.json()['candidates'][0]['content']['parts'][0]['text']
        
        pacientes_coll.update_one({"user_id": user_id, "nome": nome}, {"$push": {"consultas": {"data": datetime.now(), "relatorio": analise}}}, upsert=True)
        bot.delete_message(message.chat.id, aguarde.message_id)
        
        for i in range(0, len(analise), 2000):
            bot.send_message(message.chat.id, analise[i:i+2000], parse_mode="Markdown")
        
        path_pdf = gerar_pdf(nome, analise, nome_prof, reg_prof)
        with open(path_pdf, "rb") as f:
            bot.send_document(message.chat.id, f, caption=f"📄 Laudo: {nome}")
        os.remove(path_pdf)
        
    except:
        bot.send_message(message.chat.id, "❌ Erro na IA. Tente novamente.")

if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    bot.infinity_polling()
