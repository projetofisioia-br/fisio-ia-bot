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

# Inicialização limpa para evitar duplicação
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
bot.remove_webhook()

# Links Tapton
LINK_PRO = "https://payment-link-v3.ton.com.br/pl_rKQGmEeRapy4qQuv1TBr48Jw5z3lNo6L"
LINK_M8 = "https://payment-link-v3.ton.com.br/pl_0vDNEPpMBwoKvNIvYCEYKVjr9deXY4nG"

# --- 2. SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V7.4 Ativo"
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
        types.InlineKeyboardButton("💡 Consulta Técnica Avulsa", callback_data="consulta_avulsa"),
        types.InlineKeyboardButton("🏠 Home Care (Exercícios)", callback_data="home_care"),
        types.InlineKeyboardButton("📸 Analisar Exame", callback_data="analisar_foto"),
        types.InlineKeyboardButton("🏥 Central do Fisio", callback_data="central_fisio"),
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
    bot.send_message(m.chat.id, "🚀 **MestreFisio V7.4**\nInteligência Clínica Estável.", reply_markup=menu_principal(m.from_user.id))

@bot.callback_query_handler(func=lambda call: True)
def calls(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id) # Evita o ícone de carregamento infinito
    
    if call.data == "novo_paciente" or call.data == "consulta_avulsa":
        pode, status = verificar_acesso(uid)
        if pode:
            msg = bot.send_message(uid, "📝 Digite o nome do paciente (ou tema da consulta):")
            bot.register_next_step_handler(msg, iniciar_processo, call.data)
        else:
            bot.send_message(uid, "🚫 **Limite Atingido.** Assine para continuar.", reply_markup=menu_principal(uid))
            
    elif call.data == "assinar_premium":
        m = types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton("🏆 Plano PRO (Ilimitado) - R$ 59,90", url=LINK_PRO),
              types.InlineKeyboardButton("🩺 Plano Mestre8 (8/mês) - R$ 39,90", url=LINK_M8),
              types.InlineKeyboardButton("✅ Já paguei!", callback_data="aviso_pago"))
        bot.edit_message_text("💎 **Escolha seu Plano PhD**", uid, call.message.id, reply_markup=m)

# --- 7. IA E PROCESSAMENTO ---
def iniciar_processo(message, tipo):
    nome = message.text.upper()
    msg = bot.send_message(message.chat.id, f"✅ Selecionado: {nome}\nDescreva o caso clínico agora:")
    bot.register_next_step_handler(msg, gerar_resposta_final, nome, tipo)

def gerar_resposta_final(message, nome_p, tipo):
    uid = message.from_user.id
    aguarde = bot.send_message(message.chat.id, "🧠 Processando informação PhD...")
    u = usuarios_coll.find_one({"user_id": uid})
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
        prompt = f"Fisioterapeuta PhD. Caso: {message.text}"
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=25)
        
        if res.status_code != 200:
            bot.edit_message_text("❌ Erro na API do Google. Verifique sua API_KEY_IA nas variáveis do Render.", message.chat.id, aguarde.message_id)
            return

        txt = res.json()['candidates'][0]['content']['parts'][0]['text']
        usuarios_coll.update_one({"user_id": uid}, {"$inc": {"laudos_usados": 1}})
        
        if tipo == "novo_paciente":
            path = f"Laudo_{nome_p}.pdf"
            pdf = PDF_Relatorio(u.get('nome', 'Doutor'), u.get('registro', 'FISIO'))
            pdf.add_page()
            pdf.set_font("Arial", size=10)
            pdf.multi_cell(0, 7, txt.encode('ascii', 'ignore').decode('ascii'))
            pdf.output(path)
            bot.delete_message(message.chat.id, aguarde.message_id)
            with open(path, "rb") as f: bot.send_document(message.chat.id, f)
            os.remove(path)
        else:
            bot.edit_message_text(f"💡 **Consulta:**\n\n{txt}", message.chat.id, aguarde.message_id)
            
    except Exception as e:
        print(f"Erro: {e}")
        bot.edit_message_text("❌ Falha crítica. Tente novamente em instantes.", message.chat.id, aguarde.message_id)

if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling(timeout=20, long_polling_timeout=10)
