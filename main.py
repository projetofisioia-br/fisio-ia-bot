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
# Modelo atualizado para a versão estável mais recente
MODELO = "gemini-1.5-flash-latest" 

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
# COMANDO CRÍTICO: Remove qualquer conexão antiga antes de começar
bot.remove_webhook()

# --- 2. SERVIDOR WEB (RENDER) ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V7.5 Online"
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
        types.InlineKeyboardButton("👤 Novo Laudo PhD", callback_data="btn_laudo"),
        types.InlineKeyboardButton("💡 Consulta Técnica Avulsa", callback_data="btn_consulta"),
        types.InlineKeyboardButton("🏠 Home Care", callback_data="home_care"),
        types.InlineKeyboardButton("📸 Analisar Exame", callback_data="analisar_foto"),
        types.InlineKeyboardButton("💎 Assinar Planos", callback_data="assinar_premium")
    )
    if uid == ADMIN_ID:
        m.add(types.InlineKeyboardButton("📊 Painel Administrativo", callback_data="painel_admin"))
    return m

# --- 5. LÓGICA DE ACESSO ---
def verificar_acesso(uid):
    u = usuarios_coll.find_one({"user_id": uid})
    if not u or "nome" not in u: return False, "CADASTRO"
    if uid == ADMIN_ID: return True, "ADMIN"
    status = u.get("status", "Free")
    limite = u.get("limite_mensal", 3) if status == "Free" else u.get("limite_mensal", 8)
    usados = u.get("laudos_usados", 0)
    if usados >= limite: return False, "LIMITE"
    return True, status

# --- 6. HANDLERS ---
@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "🚀 **MestreFisio V7.5**\nPronto para sua consulta PhD.", reply_markup=menu_principal(m.from_user.id))

@bot.callback_query_handler(func=lambda call: True)
def calls(call):
    uid = call.from_user.id
    pode, status = verificar_acesso(uid)
    
    if not pode:
        bot.send_message(uid, "🚫 **Limite Gratuito Atingido.**\nAssine um plano para continuar.")
        return

    if call.data == "btn_laudo":
        msg = bot.send_message(uid, "📝 **MODO LAUDO:**\nDigite o nome do paciente:")
        bot.register_next_step_handler(msg, laudo_passo_2)
    
    elif call.data == "btn_consulta":
        msg = bot.send_message(uid, "💡 **MODO CONSULTA:**\nDescreva sua dúvida técnica ou caso clínico diretamente:")
        bot.register_next_step_handler(msg, processar_consulta_direta)

# --- 7. PROCESSAMENTO SEPARADO ---

# FLUXO DE LAUDO (NOME -> CASO -> PDF)
def laudo_passo_2(message):
    nome = message.text.upper()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: {nome}\nAgora descreva o quadro clínico para gerar o PDF:")
    bot.register_next_step_handler(msg, finalizar_laudo_pdf, nome)

def finalizar_laudo_pdf(message, nome_p):
    aguarde = bot.send_message(message.chat.id, "🧠 Gerando Laudo PhD...")
    resposta = chamar_ai(f"Fisioterapeuta PhD. Gere um laudo de 15 tópicos para o paciente {nome_p}: {message.text}")
    
    if "ERRO" in resposta:
        bot.edit_message_text(resposta, message.chat.id, aguarde.message_id)
        return

    u = usuarios_coll.find_one({"user_id": message.from_user.id})
    path = f"Laudo_{nome_p}.pdf"
    try:
        pdf = PDF_Relatorio(u.get('nome', 'Dr.'), u.get('registro', 'Fisio'))
        pdf.add_page(); pdf.set_font("Arial", size=10)
        pdf.multi_cell(0, 7, resposta.encode('ascii', 'ignore').decode('ascii'))
        pdf.output(path)
        usuarios_coll.update_one({"user_id": message.from_user.id}, {"$inc": {"laudos_usados": 1}})
        bot.delete_message(message.chat.id, aguarde.message_id)
        with open(path, "rb") as f: bot.send_document(message.chat.id, f)
        os.remove(path)
    except:
        bot.send_message(message.chat.id, "❌ Erro ao criar o arquivo PDF.")

# FLUXO DE CONSULTA (TEXTO DIRETO)
def processar_consulta_direta(message):
    aguarde = bot.send_message(message.chat.id, "🧠 Analisando sua dúvida...")
    resposta = chamar_ai(f"Fisioterapeuta PhD. Responda tecnicamente: {message.text}")
    
    if "ERRO" in resposta:
        bot.edit_message_text(resposta, message.chat.id, aguarde.message_id)
    else:
        usuarios_coll.update_one({"user_id": message.from_user.id}, {"$inc": {"laudos_usados": 1}})
        bot.edit_message_text(f"💡 **Resposta Técnica:**\n\n{resposta}", message.chat.id, aguarde.message_id)

# FUNÇÃO CENTRAL DA IA (FORMATO CORRIGIDO)
def chamar_ai(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        res = requests.post(url, json=payload, timeout=30)
        if res.status_code == 200:
            return res.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            return f"❌ ERRO API ({res.status_code}): Verifique se a chave no Render está correta e sem espaços."
    except:
        return "❌ ERRO: Falha na conexão com o Google."

if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling(timeout=30, long_polling_timeout=15)
