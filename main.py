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

# AJUSTE CRÍTICO: Modelo estável para evitar Erro 404
MODELO = "gemini-1.5-flash" 

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# Limpeza de Webhook para evitar Erro 409 (Conflito)
def resetar_conexao():
    print("🧹 Limpando conexões antigas...")
    bot.remove_webhook()
    time.sleep(2)

resetar_conexao()

# --- 2. SERVIDOR WEB (RENDER) ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V7.8 Online"
def run(): app.run(host='0.0.0.0', port=10000)

# --- 3. CLASSE PDF ---
class PDF_Relatorio(FPDF):
    def __init__(self, n, r): 
        super().__init__()
        self.n = n
        self.r = r
    def header(self):
        self.set_font('Arial','B',12)
        self.cell(0,10,'MESTREFISIO PhD - RELATORIO',0,1,'C')
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial','I',8)
        self.cell(0,10,f'Dr(a). {self.n} | {self.r}',0,0,'C')

# --- 4. MENUS ---
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

# --- 5. HANDLERS ---
@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "🚀 **MestreFisio V7.8**\nSistema PhD estabilizado.", reply_markup=menu_principal(m.from_user.id))

@bot.callback_query_handler(func=lambda call: True)
def calls(call):
    uid = call.from_user.id
    
    if call.data == "btn_laudo":
        msg = bot.send_message(uid, "📝 **MODO LAUDO:**\nDigite o nome do paciente:")
        bot.register_next_step_handler(msg, laudo_passo_2)
    
    elif call.data == "btn_consulta":
        # CORREÇÃO: Pula o nome do paciente e vai direto para a dúvida
        msg = bot.send_message(uid, "💡 **MODO CONSULTA:**\nDescreva sua dúvida técnica ou caso clínico:")
        bot.register_next_step_handler(msg, processar_consulta_direta)

# --- 6. PROCESSAMENTO ---

def laudo_passo_2(message):
    nome = message.text.upper()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: {nome}\nAgora descreva o quadro clínico para gerar o PDF:")
    bot.register_next_step_handler(msg, finalizar_laudo_pdf, nome)

def finalizar_laudo_pdf(message, nome_p):
    aguarde = bot.send_message(message.chat.id, "🧠 Gerando Laudo PhD...")
    prompt = f"Aja como um Fisioterapeuta PhD. Gere um laudo detalhado para o paciente {nome_p} baseado em: {message.text}"
    resposta = chamar_ai(prompt)
    
    if "ERRO" in resposta:
        bot.edit_message_text(resposta, message.chat.id, aguarde.message_id)
        return

    u = usuarios_coll.find_one({"user_id": message.from_user.id}) or {}
    path = f"Laudo_{nome_p}.pdf"
    try:
        pdf = PDF_Relatorio(u.get('nome', 'Dr.'), u.get('registro', 'Fisio'))
        pdf.add_page()
        pdf.set_font("Arial", size=10)
        # Latin-1 evita erros com acentos no PDF
        txt = resposta.encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(0, 7, txt)
        pdf.output(path)
        
        bot.delete_message(message.chat.id, aguarde.message_id)
        with open(path, "rb") as f:
            bot.send_document(message.chat.id, f)
        os.remove(path)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro ao gerar PDF: {e}")

def processar_consulta_direta(message):
    aguarde = bot.send_message(message.chat.id, "🧠 Analisando sua dúvida técnica...")
    prompt = f"Fisioterapeuta PhD. Responda tecnicamente de forma clara: {message.text}"
    resposta = chamar_ai(prompt)
    
    if "ERRO" in resposta:
        bot.edit_message_text(resposta, message.chat.id, aguarde.message_id)
    else:
        bot.edit_message_text(f"💡 **Resposta Técnica:**\n\n{resposta}", message.chat.id, aguarde.message_id)

# --- 7. INTEGRAÇÃO GOOGLE AI ---
def chamar_ai(prompt):
    # Rota v1beta atualizada
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    
    try:
        res = requests.post(url, json=payload, timeout=30)
        if res.status_code == 200:
            return res.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            return f"❌ ERRO API {res.status_code}: Verifique a chave e o faturamento no Google Studio."
    except Exception as e:
        return f"❌ Erro de conexão: {e}"

if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling(timeout=60, long_polling_timeout=30)
