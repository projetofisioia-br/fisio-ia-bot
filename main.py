import telebot, requests, os, time, pymongo
from telebot import types
from flask import Flask
from threading import Thread
from fpdf import FPDF
from datetime import datetime

# --- 1. CONFIGURAÇÕES E BANCO ---
MONGO_URI = os.environ.get("MONGO_URI")
client = pymongo.MongoClient(MONGO_URI)
db = client["MestreFisioDB"]
usuarios_coll = db["usuarios"]
historico_coll = db["historico_laudos"]

TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# Links Ton Reais fornecidos
LINK_M8 = "https://payment-link-v3.ton.com.br/pl_0vDNEPpMBwoKvNIvYCEYKVjr9deXY4nG"
LINK_PRO = "https://payment-link-v3.ton.com.br/pl_rKQGmEeRapy4qQuv1TBr48Jw5z3lNo6L"

# --- 2. SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V10.1 Online"
def run(): app.run(host='0.0.0.0', port=10000)

# --- 3. CLASSE PDF ---
class PDF_Laudo(FPDF):
    def __init__(self, dr_nome, registro):
        super().__init__()
        self.dr_nome = dr_nome
        self.registro = registro
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'RELATORIO FISIOTERAPEUTICO PhD', 0, 1, 'C')
        self.set_font('Arial', '', 9)
        self.cell(0, 5, f"Data: {datetime.now().strftime('%d/%m/%Y')}", 0, 1, 'R')
        self.ln(5)
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Dr(a). {self.dr_nome} | {self.registro}', 0, 0, 'C')

# --- 4. FUNÇÃO IA (CORRIGIDA) ---
def chamar_ai(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY_IA}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        res = requests.post(url, json=payload, timeout=30)
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    except:
        return "⚠️ Erro de conexão com a IA. Tente novamente."

# --- 5. MENUS ---
def menu_inicial():
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(
        types.InlineKeyboardButton("📄 Novo Laudo PhD", callback_data="laudo"),
        types.InlineKeyboardButton("💡 Consulta Técnica", callback_data="consulta"),
        types.InlineKeyboardButton("📚 Histórico de Pacientes", callback_data="ver_historico"),
        types.InlineKeyboardButton("💎 Planos de Acesso", callback_data="planos")
    )
    return m

# --- 6. FLUXO DE CADASTRO ---
@bot.message_handler(commands=['start'])
def start(m):
    user = usuarios_coll.find_one({"user_id": m.from_user.id})
    if not user:
        msg = bot.send_message(m.chat.id, "👋 Bem-vindo! Digite seu **NOME COMPLETO** para os laudos:")
        bot.register_next_step_handler(msg, salvar_nome)
    else:
        bot.send_message(m.chat.id, f"Olá, Dr(a). {user['nome']}!", reply_markup=menu_inicial())

def salvar_nome(m):
    usuarios_coll.update_one({"user_id": m.from_user.id}, {"$set": {"nome": m.text.upper()}}, upsert=True)
    msg = bot.send_message(m.chat.id, "Agora, seu **REGISTRO/CREFITO**:")
    bot.register_next_step_handler(msg, salvar_registro)

def salvar_registro(m):
    usuarios_coll.update_one({"user_id": m.from_user.id}, {"$set": {"registro": m.text.upper()}})
    bot.send_message(m.chat.id, "✅ Perfil configurado!", reply_markup=menu_inicial())

# --- 7. CALLBACKS ---
@bot.callback_query_handler(func=lambda call: True)
def tratar_callback(call):
    uid = call.from_user.id
    if call.data == "laudo":
        msg = bot.send_message(uid, "📝 Digite o **NOME DO PACIENTE**:")
        bot.register_next_step_handler(msg, laudo_passo_2)
    elif call.data == "consulta":
        msg = bot.send_message(uid, "💡 Descreva sua dúvida técnica:")
        bot.register_next_step_handler(msg, responder_consulta)
    elif call.data == "planos":
        m = types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("🥈 MestreFisio 8 (R$ 39,90)", url=LINK_M8))
        m.add(types.InlineKeyboardButton("🥇 MestreFisio Pro (R$ 59,90)", url=LINK_PRO))
        bot.send_message(uid, "💎 **Planos Disponíveis:**", reply_markup=m)
    elif call.data == "ver_historico":
        exibir_historico(call.message)

# --- 8. LÓGICA DE LAUDO E HISTÓRICO ---
def laudo_passo_2(m):
    nome_paciente = m.text.upper()
    msg = bot.send_message(m.chat.id, f"✅ Paciente: {nome_paciente}\nDescreva a avaliação clínica:")
    bot.register_next_step_handler(msg, gerar_laudo_final, nome_paciente)

def gerar_laudo_final(m, nome_p):
    aguarde = bot.send_message(m.chat.id, "🧠 Processando Laudo PhD...")
    user = usuarios_coll.find_one({"user_id": m.from_user.id})
    
    # Chamada corrigida: chamar_ai em vez de llamar_ai
    res_ia = chamar_ai(f"Gere um laudo fisioterapêutico PhD para {nome_p}: {m.text}")
    
    # Salvar no Banco
    historico_coll.insert_one({
        "user_id": m.from_user.id,
        "paciente": nome_p,
        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "conteudo": res_ia
    })

    path = f"Laudo_{nome_p}.pdf"
    try:
        pdf = PDF_Laudo(user['nome'], user['registro'])
        pdf.add_page(); pdf.set_font("Arial", size=11)
        txt = res_ia.encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(0, 10, txt)
        pdf.output(path)
        with open(path, "rb") as f: bot.send_document(m.chat.id, f)
        os.remove(path)
    except:
        bot.send_message(m.chat.id, "❌ Erro ao gerar PDF.")
    
    bot.delete_message(m.chat.id, aguarde.message_id)

def exibir_historico(m):
    docs = historico_coll.find({"user_id": m.chat.id}).sort("_id", -1).limit(5)
    texto = "📚 **Últimos 5 Pacientes:**\n\n"
    encontrou = False
    for d in docs:
        encontrou = True
        texto += f"👤 {d['paciente']}\n📅 {d['data']}\n\n"
    
    if not encontrou: texto = "Nenhum laudo encontrado no seu histórico."
    bot.send_message(m.chat.id, texto, parse_mode="Markdown")

def responder_consulta(m):
    aguarde = bot.send_message(m.chat.id, "🧠 Analisando...")
    res = chamar_ai(f"Responda como Fisioterapeuta PhD: {m.text}")
    bot.send_message(m.chat.id, f"💡 **Parecer PhD:**\n\n{res}")
    bot.delete_message(m.chat.id, aguarde.message_id)

if __name__ == "__main__":
    bot.remove_webhook()
    Thread(target=run).start()
    bot.infinity_polling(timeout=60)
