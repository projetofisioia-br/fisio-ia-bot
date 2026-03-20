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
usuarios_coll = db["usuarios"]

ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-1.5-flash-latest" 

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
bot.remove_webhook()

# --- 2. FUNÇÃO DE AUTOTESTE (VAI APARECER NO LOG DO RENDER) ---
def realizar_autoteste_api():
    print("🧪 INICIANDO AUTOTESTE DA API GOOGLE...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    payload = {"contents": [{"parts": [{"text": "Teste rápido de conexão."}]}]}
    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code == 200:
            print("✅ SUCESSO: A API do Google está aceitando sua chave!")
        else:
            print(f"❌ FALHA NA API: Código {res.status_code}")
            print(f"📝 MOTIVO DO GOOGLE: {res.text}")
    except Exception as e:
        print(f"⚠️ ERRO DE CONEXÃO: {e}")

# Executa o teste assim que o código sobe
realizar_autoteste_api()

# --- 3. SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V7.6 Online"
def run(): app.run(host='0.0.0.0', port=10000)

# --- 4. CLASSE PDF ---
class PDF_Relatorio(FPDF):
    def __init__(self, n, r): super().__init__(); self.n, self.r = n, r
    def header(self):
        self.set_font('Arial','B',12); self.cell(0,10,'MESTREFISIO PhD - RELATORIO',0,1,'C')
    def footer(self):
        self.set_y(-15); self.set_font('Arial','I',8)
        self.cell(0,10,f'Dr(a). {self.n} | {self.r}',0,0,'C')

# --- 5. MENUS ---
def menu_principal(uid):
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("👤 Novo Laudo PhD", callback_data="btn_laudo"),
        types.InlineKeyboardButton("💡 Consulta Técnica Avulsa", callback_data="btn_consulta"),
        types.InlineKeyboardButton("🏠 Home Care", callback_data="home_care"),
        types.InlineKeyboardButton("📸 Analisar Exame", callback_data="analisar_foto"),
        types.InlineKeyboardButton("💎 Assinar Planos", callback_data="assinar_premium")
    )
    if uid == ADMIN_ID:
        m.add(types.InlineKeyboardButton("📊 Painel Administrativo", callback_data="painel_admin"))
    return m

# --- 6. HANDLERS ---
@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "🚀 **MestreFisio V7.6**\nSistema de diagnóstico ativo.", reply_markup=menu_principal(m.from_user.id))

@bot.callback_query_handler(func=lambda call: True)
def calls(call):
    uid = call.from_user.id
    if call.data == "btn_laudo":
        msg = bot.send_message(uid, "📝 **MODO LAUDO:**\nDigite o nome do paciente:")
        bot.register_next_step_handler(msg, laudo_passo_2)
    elif call.data == "btn_consulta":
        msg = bot.send_message(uid, "💡 **MODO CONSULTA:**\nDescreva sua dúvida técnica:")
        bot.register_next_step_handler(msg, processar_consulta_direta)

def laudo_passo_2(message):
    nome = message.text.upper()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: {nome}\nDescreva o quadro clínico:")
    bot.register_next_step_handler(msg, finalizar_laudo_pdf, nome)

def finalizar_laudo_pdf(message, nome_p):
    aguarde = bot.send_message(message.chat.id, "🧠 Gerando Laudo PhD...")
    res_ai = chamar_ai(f"Fisioterapeuta PhD. Laudo para {nome_p}: {message.text}")
    
    if "ERRO" in res_ai:
        bot.edit_message_text(res_ai, message.chat.id, aguarde.message_id)
        return

    u = usuarios_coll.find_one({"user_id": message.from_user.id})
    path = f"Laudo_{nome_p}.pdf"
    try:
        pdf = PDF_Relatorio(u.get('nome', 'Dr.'), u.get('registro', 'Fisio'))
        pdf.add_page(); pdf.set_font("Arial", size=10)
        pdf.multi_cell(0, 7, res_ai.encode('ascii', 'ignore').decode('ascii'))
        pdf.output(path)
        bot.delete_message(message.chat.id, aguarde.message_id)
        with open(path, "rb") as f: bot.send_document(message.chat.id, f)
        os.remove(path)
    except: bot.send_message(message.chat.id, "❌ Erro ao gerar PDF.")

def processar_consulta_direta(message):
    aguarde = bot.send_message(message.chat.id, "🧠 Analisando...")
    res_ai = chamar_ai(f"Fisioterapeuta PhD. Responda: {message.text}")
    bot.edit_message_text(f"💡 **Resposta:**\n\n{res_ai}", message.chat.id, aguarde.message_id)

def chamar_ai(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    try:
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
        if res.status_code == 200:
            return res.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            return f"❌ ERRO API {res.status_code}. Verifique os logs do Render para o motivo real."
    except: return "❌ Erro de conexão."

if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling(timeout=30, long_polling_timeout=15)
