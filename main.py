import telebot, requests, os, pymongo, time
from telebot import types
from flask import Flask
from threading import Thread
from fpdf import FPDF

# --- 1. CONFIGURAÇÕES ---
MONGO_URI = os.environ.get("MONGO_URI")
client = pymongo.MongoClient(MONGO_URI)
db = client["MestreFisioDB"]
usuarios_coll = db["usuarios"]

TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")

# MODELO SEM PREFIXOS PARA MÁXIMA COMPATIBILIDADE
MODELO = "gemini-1.5-flash" 

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

def resetar_conexao():
    print("🧹 Limpando conexões antigas...")
    bot.remove_webhook()
    time.sleep(1)

resetar_conexao()

# --- 2. SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V8.0 Online"
def run(): app.run(host='0.0.0.0', port=10000)

# --- 3. CLASSE PDF ---
class PDF_Relatorio(FPDF):
    def __init__(self, n, r): 
        super().__init__()
        self.n, self.r = n, r
    def header(self):
        self.set_font('Arial','B',12); self.cell(0,10,'MESTREFISIO PhD - RELATORIO',0,1,'C')
    def footer(self):
        self.set_y(-15); self.set_font('Arial','I',8)
        self.cell(0,10,f'Dr(a). {self.n} | {self.r}',0,0,'C')

# --- 4. MENUS ---
def menu_principal():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("👤 Novo Laudo PhD", callback_data="btn_laudo"),
        types.InlineKeyboardButton("💡 Consulta Técnica Avulsa", callback_data="btn_consulta"),
        types.InlineKeyboardButton("🏠 Home Care", callback_data="home_care"),
        types.InlineKeyboardButton("📸 Analisar Exame", callback_data="analisar_foto")
    )
    return m

# --- 5. HANDLERS ---
@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "🚀 **MestreFisio V8.0**\nPronto para sua consulta PhD.", reply_markup=menu_principal())

@bot.callback_query_handler(func=lambda call: True)
def calls(call):
    if call.data == "btn_laudo":
        msg = bot.send_message(call.message.chat.id, "📝 **MODO LAUDO:** Digite o nome do paciente:")
        bot.register_next_step_handler(msg, laudo_passo_2)
    elif call.data == "btn_consulta":
        msg = bot.send_message(call.message.chat.id, "💡 **MODO CONSULTA:** Descreva seu caso ou dúvida técnica:")
        bot.register_next_step_handler(msg, processar_consulta_direta)

def laudo_passo_2(message):
    nome = message.text.upper()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: {nome}\nDescreva o quadro clínico:")
    bot.register_next_step_handler(msg, finalizar_laudo_pdf, nome)

def finalizar_laudo_pdf(message, nome_p):
    aguarde = bot.send_message(message.chat.id, "🧠 Gerando Laudo PhD...")
    res = chamar_ai(f"Gere um laudo fisioterapêutico PhD para o paciente {nome_p}: {message.text}")
    
    if "ERRO" in res:
        bot.edit_message_text(res, message.chat.id, aguarde.message_id)
        return

    path = f"Laudo_{nome_p}.pdf"
    try:
        pdf = PDF_Relatorio("Dr. Fisioterapeuta", "CREFITO-X")
        pdf.add_page(); pdf.set_font("Arial", size=10)
        pdf.multi_cell(0, 7, res.encode('latin-1', 'replace').decode('latin-1'))
        pdf.output(path)
        bot.delete_message(message.chat.id, aguarde.message_id)
        with open(path, "rb") as f: bot.send_document(message.chat.id, f)
        os.remove(path)
    except: bot.send_message(message.chat.id, "❌ Erro ao gerar o arquivo PDF.")

def processar_consulta_direta(message):
    aguarde = bot.send_message(message.chat.id, "🧠 Analisando...")
    res = chamar_ai(f"Responda como Fisioterapeuta PhD: {message.text}")
    bot.edit_message_text(f"💡 **Resposta PhD:**\n\n{res}", message.chat.id, aguarde.message_id)

# --- 6. INTEGRAÇÃO GOOGLE AI (CORREÇÃO 404) ---
def chamar_ai(prompt):
    # USANDO A ROTA V1 ESTÁVEL
    url = f"https://generativelanguage.googleapis.com/v1/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        res = requests.post(url, json=payload, timeout=30)
        if res.status_code == 200:
            return res.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            return f"❌ ERRO API {res.status_code}: Verifique se a API Gemini está ATIVA no seu Google Cloud Console."
    except:
        return "❌ Erro de conexão com a inteligência PhD."

if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling(timeout=60)
