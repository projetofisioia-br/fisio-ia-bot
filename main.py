import telebot, requests, os, time, pymongo
from telebot import types
from flask import Flask
from threading import Thread
from fpdf import FPDF
from datetime import datetime

# --- 1. CONFIGURAÇÕES ---
MONGO_URI = os.environ.get("MONGO_URI")
client = pymongo.MongoClient(MONGO_URI)
db = client["MestreFisioDB"]
usuarios_coll = db["usuarios"]
historico_coll = db["historico_laudos"]

TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# Links Ton Reais
LINK_M8 = "https://payment-link-v3.ton.com.br/pl_0vDNEPpMBwoKvNIvYCEYKVjr9deXY4nG"
LINK_PRO = "https://payment-link-v3.ton.com.br/pl_rKQGmEeRapy4qQuv1TBr48Jw5z3lNo6L"

# VARIÁVEL GLOBAL QUE O DIAGNÓSTICO VAI PREENCHER
MODELO_ATIVO = "gemini-1.5-flash" 

# --- 2. RASTREAMENTO INTERNO (LOGS DO RENDER) ---
def diagnostico_ia():
    global MODELO_ATIVO
    print("\n🔍 --- INICIANDO RASTREAMENTO DE IA ---")
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY_IA}"
    
    try:
        res = requests.get(url, timeout=15)
        if res.status_code == 200:
            modelos = res.json().get('models', [])
            nomes = [m['name'].split('/')[-1] for m in modelos if 'generateContent' in m['supportedGenerationMethods']]
            print(f"✅ MODELOS DISPONÍVEIS NA SUA CHAVE: {nomes}")
            
            # Escolhe o melhor disponível automaticamente
            if "gemini-1.5-flash" in nomes: MODELO_ATIVO = "gemini-1.5-flash"
            elif "gemini-1.5-pro" in nomes: MODELO_ATIVO = "gemini-1.5-pro"
            elif "gemini-pro" in nomes: MODELO_ATIVO = "gemini-pro"
            else: MODELO_ATIVO = nomes[0] if nomes else "gemini-1.5-flash"
            
            print(f"🚀 O BOT USARÁ O MODELO: {MODELO_ATIVO}")
        else:
            print(f"❌ ERRO DE AUTORIZAÇÃO (401/403): {res.text}")
            print("👉 DICA: Verifique se copiou a chave sem espaços no Render.")
    except Exception as e:
        print(f"⚠️ ERRO DE CONEXÃO NO DIAGNÓSTICO: {e}")
    print("--- FIM DO RASTREAMENTO ---\n")

# --- 3. SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return f"MestreFisio V11.0 - Ativo com {MODELO_ATIVO}"
def run(): app.run(host='0.0.0.0', port=10000)

# --- 4. FUNÇÃO IA ---
def chamar_ai(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO_ATIVO}:generateContent?key={API_KEY_IA}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        res = requests.post(url, json=payload, timeout=30)
        if res.status_code == 200:
            return res.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            return f"⚠️ Erro {res.status_code} na IA. Verifique os logs do Render."
    except:
        return "⚠️ O servidor de IA não respondeu a tempo."

# --- 5. CLASSE PDF ---
class PDF_Laudo(FPDF):
    def __init__(self, dr_nome, registro):
        super().__init__()
        self.dr_nome, self.registro = dr_nome, registro
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'RELATORIO FISIOTERAPEUTICO PhD', 0, 1, 'C')
        self.ln(5)
    def footer(self):
        self.set_y(-15); self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Dr(a). {self.dr_nome} | {self.registro}', 0, 0, 'C')

# --- 6. INTERFACE E LOGICA (START, CADASTRO, HISTÓRICO) ---
@bot.message_handler(commands=['start'])
def start(m):
    user = usuarios_coll.find_one({"user_id": m.from_user.id})
    if not user:
        msg = bot.send_message(m.chat.id, "👋 Olá! Digite seu **NOME COMPLETO** para o cadastro:")
        bot.register_next_step_handler(msg, salvar_nome)
    else:
        m_ini = types.InlineKeyboardMarkup(row_width=1)
        m_ini.add(
            types.InlineKeyboardButton("📄 Novo Laudo PhD", callback_data="laudo"),
            types.InlineKeyboardButton("💡 Consulta Técnica", callback_data="consulta"),
            types.InlineKeyboardButton("📚 Histórico de Pacientes", callback_data="ver_historico"),
            types.InlineKeyboardButton("💎 Planos de Acesso", callback_data="planos")
        )
        bot.send_message(m.chat.id, f"Olá, Dr(a). {user['nome']}!", reply_markup=m_ini)

def salvar_nome(m):
    usuarios_coll.update_one({"user_id": m.from_user.id}, {"$set": {"nome": m.text.upper()}}, upsert=True)
    msg = bot.send_message(m.chat.id, "Agora, seu **REGISTRO/CREFITO**:")
    bot.register_next_step_handler(msg, salvar_registro)

def salvar_registro(m):
    usuarios_coll.update_one({"user_id": m.from_user.id}, {"$set": {"registro": m.text.upper()}})
    bot.send_message(m.chat.id, "✅ Perfil pronto!", reply_markup=types.ReplyKeyboardRemove())
    start(m)

@bot.callback_query_handler(func=lambda call: True)
def tratar_callback(call):
    uid = call.from_user.id
    if call.data == "laudo":
        msg = bot.send_message(uid, "📝 Nome do Paciente:")
        bot.register_next_step_handler(msg, laudo_p2)
    elif call.data == "ver_historico":
        docs = historico_coll.find({"user_id": uid}).sort("_id", -1).limit(5)
        txt = "📚 **Últimos Laudos:**\n\n"
        for d in docs: txt += f"👤 {d['paciente']} - {d['data']}\n"
        bot.send_message(uid, txt if "👤" in txt else "Histórico vazio.")
    elif call.data == "planos":
        m = types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("🥈 MestreFisio 8 (R$ 39,90)", url=LINK_M8))
        m.add(types.InlineKeyboardButton("🥇 MestreFisio Pro (R$ 59,90)", url=LINK_PRO))
        bot.send_message(uid, "💎 Escolha seu plano:", reply_markup=m)

def laudo_p2(m):
    nome_p = m.text.upper()
    msg = bot.send_message(m.chat.id, f"✅ Paciente: {nome_p}\nDescreva o caso clínico:")
    bot.register_next_step_handler(msg, gerar_laudo, nome_p)

def gerar_laudo(m, nome):
    aguarde = bot.send_message(m.chat.id, "🧠 Gerando...")
    user = usuarios_coll.find_one({"user_id": m.from_user.id})
    res_ia = chamar_ai(f"Laudo PhD para {nome}: {m.text}")
    
    historico_coll.insert_one({"user_id": m.from_user.id, "paciente": nome, "data": datetime.now().strftime("%d/%m/%Y"), "conteudo": res_ia})
    
    path = f"{nome}.pdf"
    pdf = PDF_Laudo(user['nome'], user['registro'])
    pdf.add_page(); pdf.set_font("Arial", size=11)
    pdf.multi_cell(0, 10, res_ia.encode('latin-1', 'replace').decode('latin-1'))
    pdf.output(path)
    
    with open(path, "rb") as f: bot.send_document(m.chat.id, f)
    os.remove(path)
    bot.delete_message(m.chat.id, aguarde.message_id)

# --- 7. EXECUÇÃO ---
if __name__ == "__main__":
    diagnostico_ia() # Roda o rastreio nos logs
    bot.remove_webhook()
    Thread(target=run).start()
    bot.infinity_polling(timeout=60)
