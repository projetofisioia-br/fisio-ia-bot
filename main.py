import telebot, requests, os, pymongo, time
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

# INICIALIZAÇÃO COM LIMPEZA FORÇADA
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

def resetar_conexao():
    print("🧹 Removendo conexões antigas do Telegram...")
    bot.remove_webhook()
    time.sleep(2) # Pausa estratégica para o Telegram processar a desconexão

resetar_conexao()

# --- 2. AUTODIAGNÓSTICO DA CHAVE ---
def autoteste_google():
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    payload = {"contents": [{"parts": [{"text": "Teste"}]}]}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print("✅ GOOGLE API: Chave funcionando perfeitamente!")
        else:
            print(f"❌ GOOGLE API ERRO {res.status_code}: {res.text}")
    except Exception as e:
        print(f"⚠️ ERRO DE CONEXÃO GOOGLE: {e}")

autoteste_google()

# --- 3. SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V7.7 Ativo"
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
    bot.send_message(m.chat.id, "🚀 **MestreFisio V7.7**\nConexão limpa e estabilizada.", reply_markup=menu_principal(m.from_user.id))

@bot.callback_query_handler(func=lambda call: True)
def calls(call):
    uid = call.from_user.id
    if call.data == "btn_laudo":
        msg = bot.send_message(uid, "📝 **NOME DO PACIENTE:**")
        bot.register_next_step_handler(msg, laudo_passo_2)
    elif call.data == "btn_consulta":
        msg = bot.send_message(uid, "💡 **SUA DÚVIDA TÉCNICA:**")
        bot.register_next_step_handler(msg, processar_consulta_direta)

def laudo_passo_2(message):
    nome = message.text.upper()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: {nome}\nDescreva o caso clínico:")
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
        pdf.multi_cell(0, 7, res_ai.encode('latin-1', 'replace').decode('latin-1'))
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
            return f"❌ ERRO API {res.status_code}: Verifique a chave e o faturamento no Google AI Studio."
    except: return "❌ Erro de conexão com a IA."

if __name__ == "__main__":
    Thread(target=run).start()
    # Polling com intervalo para evitar Erro 409
    bot.infinity_polling(timeout=60, long_polling_timeout=30)
