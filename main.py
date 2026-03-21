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

# DEFINIMOS O MODELO QUE APARECEU NO SEU RASTREIO
MODELO_ATIVO = "gemini-2.5-flash" 

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# Links Ton Reais
LINK_M8 = "https://payment-link-v3.ton.com.br/pl_0vDNEPpMBwoKvNIvYCEYKVjr9deXY4nG"
LINK_PRO = "https://payment-link-v3.ton.com.br/pl_rKQGmEeRapy4qQuv1TBr48Jw5z3lNo6L"

# --- 2. SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return f"MestreFisio V12.1 - Online com {MODELO_ATIVO}"
def run(): app.run(host='0.0.0.0', port=10000)

# --- 3. FUNÇÃO IA (ATUALIZADA COM FILTROS LIBERADOS) ---
def chamar_ai(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO_ATIVO}:generateContent?key={API_KEY_IA}"
    
    payload = {
        "contents": [{"parts": [{"text": f"Responda como um Fisioterapeuta PhD: {prompt}"}]}],
      "generationConfig": {
            "temperature": 0.3, # Reduzimos para ser mais rápido e preciso
            "maxOutputTokens": 2048, # Aumentamos para suportar textos bem longos
            "topP": 0.8,
            "topK": 40
        },

        # Adicionado para evitar que o Google bloqueie termos de saúde/clínicos
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }
    headers = {'Content-Type': 'application/json'}
    
    try:
        # Aumentamos o timeout para 60 segundos para casos clínicos longos
        res = requests.post(url, json=payload, headers=headers, timeout=60)
        if res.status_code == 200:
            return res.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            print(f"Erro IA {res.status_code}: {res.text}")
            return f"⚠️ Erro técnico {res.status_code}. Verifique a chave no Render."
    except Exception as e:
        print(f"Erro Conexão IA: {e}")
        return "⚠️ O servidor PhD demorou a responder. Tente novamente em instantes."

# --- 4. CLASSE PDF ---
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

# --- 5. INTERFACE E FLUXO ---
def menu_principal():
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(
        types.InlineKeyboardButton("📄 Novo Laudo PhD (PDF)", callback_data="laudo"),
        types.InlineKeyboardButton("💡 Consulta Técnica PhD", callback_data="consulta"),
        types.InlineKeyboardButton("📚 Histórico de Pacientes", callback_data="ver_historico"),
        types.InlineKeyboardButton("💎 Planos de Acesso", callback_data="planos")
    )
    return m

@bot.message_handler(commands=['start'])
def start(m):
    user = usuarios_coll.find_one({"user_id": m.from_user.id})
    if not user:
        msg = bot.send_message(m.chat.id, "👋 Bem-vindo! Digite seu **NOME COMPLETO** para os laudos:")
        bot.register_next_step_handler(msg, salvar_nome)
    else:
        bot.send_message(m.chat.id, f"Olá, Dr(a). {user['nome']}! Como posso ajudar?", reply_markup=menu_principal())

def salvar_nome(m):
    usuarios_coll.update_one({"user_id": m.from_user.id}, {"$set": {"nome": m.text.upper()}}, upsert=True)
    msg = bot.send_message(m.chat.id, "Agora, informe seu **REGISTRO/CREFITO**:")
    bot.register_next_step_handler(msg, salvar_registro)

def salvar_registro(m):
    usuarios_coll.update_one({"user_id": m.from_user.id}, {"$set": {"registro": m.text.upper()}})
    bot.send_message(m.chat.id, "✅ Perfil configurado com sucesso!", reply_markup=menu_principal())

@bot.callback_query_handler(func=lambda call: True)
def tratar_callback(call):
    uid = call.from_user.id
    if call.data == "laudo":
        msg = bot.send_message(uid, "📝 Digite o **NOME DO PACIENTE**:")
        bot.register_next_step_handler(msg, laudo_p2)
    elif call.data == "consulta":
        msg = bot.send_message(uid, "💡 Descreva sua dúvida técnica:")
        bot.register_next_step_handler(msg, responder_consulta)
    elif call.data == "ver_historico":
        docs = historico_coll.find({"user_id": uid}).sort("_id", -1).limit(5)
        txt = "📚 **Últimos Atendimentos:**\n\n"
        encontrou = False
        for d in docs:
            encontrou = True
            txt += f"👤 {d['paciente']} — 📅 {d['data']}\n"
        bot.send_message(uid, txt if encontrou else "Nenhum laudo no histórico.")
    elif call.data == "planos":
        m = types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("🥈 MestreFisio 8 (R$ 39,90)", url=LINK_M8))
        m.add(types.InlineKeyboardButton("🥇 MestreFisio Pro (R$ 59,90)", url=LINK_PRO))
        bot.send_message(uid, "💎 **Escolha seu plano de acesso:**", reply_markup=m)

# --- 6. LÓGICA DE GERAÇÃO ---
def laudo_p2(m):
    nome_p = m.text.upper()
    msg = bot.send_message(m.chat.id, f"✅ Paciente: {nome_p}\nAgora, descreva a avaliação ou caso clínico:")
    bot.register_next_step_handler(msg, concluir_laudo, nome_p)

def concluir_laudo(m, nome):
    aguarde = bot.send_message(m.chat.id, "🧠 Gerando Laudo PhD e PDF...")
    user = usuarios_coll.find_one({"user_id": m.from_user.id})
    res_ia = chamar_ai(f"Gere um laudo detalhado para o paciente {nome}: {m.text}")
    
    historico_coll.insert_one({
        "user_id": m.from_user.id,
        "paciente": nome,
        "data": datetime.now().strftime("%d/%m/%Y"),
        "conteudo": res_ia
    })
    
    path = f"Laudo_{nome}.pdf"
    try:
        pdf = PDF_Laudo(user['nome'], user['registro'])
        pdf.add_page(); pdf.set_font("Arial", size=11)
        txt_pdf = res_ia.encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(0, 10, txt_pdf)
        pdf.output(path)
        with open(path, "rb") as f: bot.send_document(m.chat.id, f)
        os.remove(path)
    except Exception as e:
        bot.send_message(m.chat.id, "❌ Erro ao gerar PDF. Mas o laudo foi salvo no histórico.")
    
    bot.delete_message(m.chat.id, aguarde.message_id)

def responder_consulta(m):
    aguarde = bot.send_message(m.chat.id, "🧠 Consultando base PhD...")
    res = chamar_ai(m.text)
    bot.send_message(m.chat.id, f"💡 **Parecer Técnico:**\n\n{res}")
    bot.delete_message(m.chat.id, aguarde.message_id)

# --- 7. INICIALIZAÇÃO ---
if __name__ == "__main__":
    # Limpa webhooks antigos
    requests.get(f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/deleteWebhook")
    
    Thread(target=run).start()
    print(f"✅ Bot iniciado com {MODELO_ATIVO}")
    bot.infinity_polling(timeout=60, skip_pending=True)
