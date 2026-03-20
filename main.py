import telebot, requests, os, pymongo, io, base64
from telebot import types
from flask import Flask
from threading import Thread
from datetime import datetime
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

# Links de Cobrança Tapton
LINK_PRO = "https://payment-link-v3.ton.com.br/pl_rKQGmEeRapy4qQuv1TBr48Jw5z3lNo6L"
LINK_M8 = "https://payment-link-v3.ton.com.br/pl_0vDNEPpMBwoKvNIvYCEYKVjr9deXY4nG"

# --- 2. SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V7.2 Online"
def run(): app.run(host='0.0.0.0', port=10000)

# --- 3. CLASSE PDF ---
class PDF_Relatorio(FPDF):
    def __init__(self, n, r): super().__init__(); self.n, self.r = n, r
    def header(self):
        self.set_font('Arial','B',12); self.cell(0,10,'MESTREFISIO PhD - RELATORIO',0,1,'C')
    def footer(self):
        self.set_y(-15); self.set_font('Arial','I',8)
        self.cell(0,10,f'Dr(a). {self.n} | {self.r}',0,0,'C')

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
    return m

# --- 5. LOGICA DE ACESSO (3 CONSULTAS GRÁTIS) ---
def verificar_acesso(uid):
    u = usuarios_coll.find_one({"user_id": uid})
    if not u or "nome" not in u: return False, "CADASTRO"
    if uid == ADMIN_ID: return True, "ADMIN"
    
    status = u.get("status", "Free")
    # Limite é 3 para grátis, ou o limite do plano contratado
    limite = u.get("limite_mensal", 3) if status == "Free" else u.get("limite_mensal", 8)
    usados = u.get("laudos_usados", 0)
    
    if usados >= limite: return False, "LIMITE"
    return True, status

# --- 6. COMANDOS ---
@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "🚀 **MestreFisio V7.2**\nSua inteligência clínica PhD.", reply_markup=menu_principal(m.from_user.id))

@bot.message_handler(commands=['liberar']) # Comando exclusivo do Admin
def comando_liberar(m):
    if m.from_user.id == ADMIN_ID:
        try:
            _, target_id, plano = m.text.split()
            limite = 9999 if plano.upper() == "PRO" else 8
            usuarios_coll.update_one({"user_id": int(target_id)}, {"$set": {"status": "Premium", "plano": plano.upper(), "limite_mensal": limite, "laudos_usados": 0}}, upsert=True)
            bot.send_message(int(target_id), f"💎 **ACESSO ATIVADO!**\nSeu plano {plano.upper()} está pronto para uso.")
            bot.send_message(ADMIN_ID, f"✅ Usuário {target_id} liberado com sucesso.")
        except: bot.reply_to(m, "Use: /liberar ID PLANO (Ex: /liberar 12345678 PRO)")

# --- 7. HANDLERS ---
@bot.callback_query_handler(func=lambda call: True)
def calls(call):
    uid = call.from_user.id
    if call.data == "assinar_premium":
        m = types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton("🏆 Plano PRO (Ilimitado) - R$ 59,90", url=LINK_PRO),
              types.InlineKeyboardButton("🩺 Plano Mestre8 (8/mês) - R$ 39,90", url=LINK_M8),
              types.InlineKeyboardButton("✅ Já paguei! Enviar Comprovante", callback_data="aviso_pago"))
        bot.edit_message_text("💎 **Planos MestreFisio PhD**\n\nInvista na sua produtividade clínica.", uid, call.message.id, reply_markup=m)

    elif call.data == "aviso_pago":
        bot.send_message(uid, f"✅ **Aviso recebido!** Envie o print do comprovante agora. Seu ID: `{uid}`")
        bot.send_message(ADMIN_ID, f"⚠️ **PAGAMENTO PENDENTE**\nUsuário `{uid}` afirma que pagou. Verifique o comprovante!")

    elif call.data == "novo_paciente":
        pode, status = verificar_acesso(uid)
        if pode:
            msg = bot.send_message(uid, "📝 Nome do Paciente:")
            bot.register_next_step_handler(msg, iniciar_laudo)
        else:
            bot.send_message(uid, "🚫 **Limite Gratuito Atingido (3/3)**\nAssine um plano para continuar gerando laudos PhD ilimitados.", reply_markup=menu_principal(uid))

    elif call.data == "home_care":
        msg = bot.send_message(uid, "🏠 **HOME CARE**\nDescreva a patologia e o nível do paciente para eu gerar os exercícios:")
        bot.register_next_step_handler(msg, processar_home_care)

# --- 8. PROCESSAMENTOS IA ---
def processar_home_care(message):
    aguarde = bot.send_message(message.chat.id, "🧠 Criando programa Home Care...")
    prompt = f"Fisioterapeuta PhD. Crie uma lista de 5 exercícios domiciliares para: {message.text}. Explique execução e repetições."
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}).json()
        resposta = res['candidates'][0]['content']['parts'][0]['text']
        bot.edit_message_text(f"🏠 **Programa Home Care:**\n\n{resposta}", message.chat.id, aguarde.message_id)
    except: bot.send_message(message.chat.id, "❌ Erro ao gerar exercícios.")

@bot.message_handler(content_types=['photo'])
def ler_exame(message):
    uid = message.from_user.id
    pode, _ = verificar_acesso(uid)
    if not pode: 
        bot.send_message(uid, "🚫 Função exclusiva para assinantes."); return
    
    aguarde = bot.send_message(uid, "🧠 Analisando imagem...")
    f_info = bot.get_file(message.photo[-1].file_id)
    img = requests.get(f'https://api.telegram.org/file/bot{TOKEN_TELEGRAM}/{f_info.file_path}').content
    img_b64 = base64.b64encode(img).decode('utf-8')
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
        payload = {"contents": [{"parts": [{"text": "Interprete os achados deste exame para um fisioterapeuta PhD:"}, {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}]}]}
        res = requests.post(url, json=payload).json()
        bot.edit_message_text(f"📋 **Análise PhD:**\n\n{res['candidates'][0]['content']['parts'][0]['text']}", uid, aguarde.message_id)
    except: bot.send_message(uid, "❌ Erro na leitura da imagem.")

def iniciar_laudo(message):
    nome = message.text.upper()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: {nome}\nDescreva o quadro clínico:")
    bot.register_next_step_handler(msg, gerar_laudo_final, nome)

def gerar_laudo_final(message, nome_p):
    uid = message.from_user.id; aguarde = bot.send_message(message.chat.id, "🧠 Gerando Laudo PhD...")
    u = usuarios_coll.find_one({"user_id": uid})
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
        res = requests.post(url, json={"contents": [{"parts": [{"text": f"Fisioterapeuta PhD. Laudo de 15 tópicos para {nome_p}: {message.text}"}]}]}).json()
        txt = res['candidates'][0]['content']['parts'][0]['text']
        pacientes_coll.update_one({"user_id": uid, "nome": nome_p}, {"$push": {"consultas": {"data": datetime.now(), "txt": txt}}}, upsert=True)
        usuarios_coll.update_one({"user_id": uid}, {"$inc": {"laudos_usados": 1}})
        path = f"Laudo_{nome_p}.pdf"; pdf = PDF_Relatorio(u['nome'], u['registro']); pdf.add_page()
        pdf.set_font("Arial", size=10); pdf.multi_cell(0, 7, txt.encode('ascii', 'ignore').decode('ascii'))
        pdf.output(path); bot.delete_message(message.chat.id, aguarde.message_id)
        with open(path, "rb") as f: bot.send_document(message.chat.id, f)
        os.remove(path)
    except: bot.send_message(message.chat.id, "❌ Erro ao gerar laudo.")

if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling()
