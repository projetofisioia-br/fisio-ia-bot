import telebot, requests, os, pymongo, io, base64, csv
from telebot import types
from flask import Flask
from threading import Thread
from datetime import datetime, timedelta
from fpdf import FPDF

# --- 1. CONFIGURAÇÕES ---
MONGO_URI = os.environ.get("MONGO_URI")
client = pymongo.MongoClient(MONGO_URI)
db = client["MestreFisioDB"]
pacientes_coll = db["pacientes"]
usuarios_coll = db["usuarios"]

ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-1.5-flash"
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# Links Tapton
LINK_PRO = "https://payment-link-v3.ton.com.br/pl_rKQGmEeRapy4qQuv1TBr48Jw5z3lNo6L"
LINK_M8 = "https://payment-link-v3.ton.com.br/pl_0vDNEPpMBwoKvNIvYCEYKVjr9deXY4nG"

# --- 2. SERVIDOR WEB (ESTÁVEL NO PLANO STARTER) ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V7.2 Ativo"

def run(): app.run(host='0.0.0.0', port=10000)

# --- 3. CLASSE PDF ---
class PDF_Relatorio(FPDF):
    def __init__(self, n, r): super().__init__(); self.n, self.r = n, r
    def header(self):
        self.set_font('Arial','B',12)
        self.cell(0,10,'MESTREFISIO PhD - INTELIGENCIA CLINICA',0,1,'C')
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial','I',8)
        self.cell(0,10,f'Documento gerado por {self.n} | {self.r}',0,0,'C')

# --- 4. MENUS ---
def menu_principal(uid):
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("👤 Novo Laudo PhD", callback_data="novo_paciente"),
        types.InlineKeyboardButton("🏠 Home Care (Exercícios)", callback_data="home_care"),
        types.InlineKeyboardButton("📸 Analisar Exame", callback_data="analisar_foto"),
        types.InlineKeyboardButton("🏥 Central do Fisio", callback_data="central_fisio"),
        types.InlineKeyboardButton("💎 Assinar Planos", callback_data="assinar_premium")
    )
    if uid == ADMIN_ID:
        m.add(types.InlineKeyboardButton("📊 Painel Admin", callback_data="painel_admin"))
    return m

def menu_central(uid):
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(
        types.InlineKeyboardButton("📋 Histórico por Paciente", callback_data="exportar_paciente"),
        types.InlineKeyboardButton("🧬 Filtro por Patologia", callback_data="filtro_patologia"),
        types.InlineKeyboardButton("📊 Meu Perfil/Uso", callback_data="meu_perfil"),
        types.InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")
    )
    return m

# --- 5. LOGICA DE SEGURANÇA E PLANOS ---
def verificar_acesso(uid):
    u = usuarios_coll.find_one({"user_id": uid})
    if not u or "nome" not in u: return False, "CADASTRO", None
    
    if uid == ADMIN_ID: return True, "ADMIN", u
    
    status = u.get("status", "Free")
    limite = u.get("limite_mensal", 3)
    usados = u.get("laudos_usados", 0)
    
    if usados >= limite: return False, "LIMITE", u
    return True, status, u

# --- 6. COMANDOS ---
@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "🚀 **MestreFisio V7.2**\nSua inteligência clínica PhD.", reply_markup=menu_principal(m.from_user.id))

@bot.message_handler(commands=['liberar']) # Comando para você usar
def comando_liberar(m):
    if m.from_user.id == ADMIN_ID:
        try:
            _, target_id, plano = m.text.split()
            limite = 9999 if plano.upper() == "PRO" else 8
            usuarios_coll.update_one({"user_id": int(target_id)}, {"$set": {"status": "Premium", "plano": plano.upper(), "limite_mensal": limite, "laudos_usados": 0}}, upsert=True)
            bot.send_message(ADMIN_ID, f"✅ Usuário {target_id} liberado no plano {plano.upper()}!")
            bot.send_message(int(target_id), f"💎 **PARABÉNS!** Seu acesso ao MestreFisio {plano.upper()} foi ativado!")
        except: bot.reply_to(m, "Use: /liberar ID PLANO (Ex: /liberar 12345 PRO)")

# --- 7. CALLBACKS ---
@bot.callback_query_handler(func=lambda call: True)
def calls(call):
    uid = call.from_user.id
    if call.data == "voltar":
        bot.edit_message_text("🚀 Menu Principal:", uid, call.message.id, reply_markup=menu_principal(uid))
    
    elif call.data == "assinar_premium":
        m = types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton("🏆 Plano PRO (Ilimitado) - R$ 59,90", url=LINK_PRO),
              types.InlineKeyboardButton("🩺 Plano Mestre8 (8/mês) - R$ 39,90", url=LINK_M8),
              types.InlineKeyboardButton("✅ Já paguei! Enviar Comprovante", callback_data="aviso_pagamento"))
        bot.edit_message_text("💎 **Escolha seu Plano PhD**\n\nInvista na sua produtividade clínica.", uid, call.message.id, reply_markup=m)

    elif call.data == "aviso_pagamento":
        bot.send_message(uid, f"🔔 **Aviso enviado!**\nEnvie o comprovante abaixo. Seu ID para liberação é: `{uid}`")
        bot.send_message(ADMIN_ID, f"⚠️ **ALERTA DE PAGAMENTO!**\nUsuário `{uid}` afirma que pagou. Aguarde o comprovante.")

    elif call.data == "central_fisio":
        bot.edit_message_text("🏥 **Central do Fisioterapeuta**", uid, call.message.id, reply_markup=menu_central(uid))

    elif call.data == "novo_paciente":
        pode, status, _ = verificar_acesso(uid)
        if pode:
            msg = bot.send_message(uid, "📝 Nome do Paciente:")
            bot.register_next_step_handler(msg, iniciar_laudo)
        else: bot.send_message(uid, "🚫 Limite atingido ou cadastro pendente. Assine um plano!")

    elif call.data == "home_care":
        msg = bot.send_message(uid, "🏠 **HOME CARE**\nDescreva a patologia e o nível do paciente para eu gerar a lista de exercícios:")
        bot.register_next_step_handler(msg, processar_home_care)

    elif call.data == "analisar_foto":
        bot.send_message(uid, "📸 Envie a foto nítida do exame/laudo para interpretação PhD.")

# --- 8. PROCESSAMENTOS IA ---
def processar_home_care(message):
    aguarde = bot.send_message(message.chat.id, "🧠 Criando programa Home Care...")
    prompt = f"Fisioterapeuta PhD. Crie uma lista de 5 exercícios domiciliares simples e seguros para: {message.text}. Explique a execução e repetições."
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}).json()
        resposta = res['candidates'][0]['content']['parts'][0]['text']
        bot.edit_message_text(f"🏠 **Programa Home Care:**\n\n{resposta}", message.chat.id, aguarde.message_id)
    except: bot.send_message(message.chat.id, "❌ Erro ao gerar exercícios.")

@bot.message_handler(content_types=['photo'])
def ler_exame(message):
    uid = message.from_user.id
    aguarde = bot.send_message(uid, "🧠 Lendo exame...")
    f_info = bot.get_file(message.photo[-1].file_id)
    img = requests.get(f'https://api.telegram.org/file/bot{TOKEN_TELEGRAM}/{f_info.file_path}').content
    img_b64 = base64.b64encode(img).decode('utf-8')
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
        payload = {"contents": [{"parts": [{"text": "Interprete este exame para um fisioterapeuta:"}, {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}]}]}
        res = requests.post(url, json=payload).json()
        bot.edit_message_text(f"📋 **Análise:**\n{res['candidates'][0]['content']['parts'][0]['text']}", uid, aguarde.message_id)
    except: bot.send_message(uid, "❌ Erro na leitura.")

def iniciar_laudo(message):
    nome = message.text.upper(); msg = bot.send_message(message.chat.id, f"✅ Paciente: {nome}\nDescreva o caso:")
    bot.register_next_step_handler(msg, gerar_laudo_final, nome)

def gerar_laudo_final(message, nome_p):
    uid = message.from_user.id; aguarde = bot.send_message(message.chat.id, "🧠 Gerando Laudo...")
    u = usuarios_coll.find_one({"user_id": uid})
    prompt = f"Fisioterapeuta PhD. Relatório de 15 tópicos para {nome_p}: {message.text}"
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}).json()
        txt = res['candidates'][0]['content']['parts'][0]['text']
        pacientes_coll.update_one({"user_id": uid, "nome": nome_p}, {"$push": {"consultas": {"data": datetime.now(), "txt": txt}}}, upsert=True)
        usuarios_coll.update_one({"user_id": uid}, {"$inc": {"laudos_usados": 1}})
        path = f"Laudo_{nome_p}.pdf"; pdf = PDF_Relatorio(u['nome'], u['registro']); pdf.add_page()
        pdf.set_font("Arial", size=10); pdf.multi_cell(0, 7, txt.encode('ascii', 'ignore').decode('ascii'))
        pdf.output(path); bot.delete_message(message.chat.id, aguarde.message_id)
        with open(path, "rb") as f: bot.send_document(message.chat.id, f)
        os.remove(path)
    except: bot.send_message(message.chat.id, "❌ Erro no laudo.")

if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling()
