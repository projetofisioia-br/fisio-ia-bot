import telebot, requests, os, time, pymongo, csv
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
MODELO = "gemini-1.5-flash" # Versão otimizada para velocidade
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# --- 2. SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V6.2 - BI Mode"

def run(): app.run(host='0.0.0.0', port=10000)

# --- 3. CLASSE PDF (Reforçada) ---
class PDF_Relatorio(FPDF):
    def __init__(self, nome_prof, registro_prof):
        super().__init__()
        self.nome_prof = nome_prof
        self.registro_prof = registro_prof

    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'MESTREFISIO - RELATORIO PhD', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Prof: {self.nome_prof} | {self.registro_prof}', 0, 0, 'C')

# --- 4. SEGURANÇA E LIMITES ---
def verificar_registro(user_id, chat_id):
    perfil = usuarios_coll.find_one({"user_id": user_id})
    if not perfil:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✍️ Configurar Perfil", callback_data="config_perfil"))
        bot.send_message(chat_id, "⚠️ **Cadastro Necessário**\nConfigure seu perfil para liberar as funções.", reply_markup=markup)
        return False, None
    return True, perfil

def verificar_limite(user_id, perfil):
    if user_id == ADMIN_ID: return True, 0
    uso = perfil.get("laudos_usados", 0)
    if uso >= 3: return False, uso
    return True, uso

# --- 5. INTERFACE ---
def menu_principal(user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👤 Novo Paciente / Laudo PhD", callback_data="novo_paciente"),
        types.InlineKeyboardButton("💡 Consulta Técnica Avulsa", callback_data="consulta_avulsa"),
        types.InlineKeyboardButton("📋 Meus Pacientes", callback_data="listar_pacientes"),
        types.InlineKeyboardButton("⚙️ Configurar Meu Perfil", callback_data="config_perfil")
    )
    if user_id == ADMIN_ID:
        markup.add(types.InlineKeyboardButton("📊 Painel Administrativo", callback_data="painel_admin"))
    return markup

# --- 6. COMANDOS ---
@bot.message_handler(commands=['start'])
def welcome(message):
    user_id = message.from_user.id
    # Captura origem por link: t.me/bot?start=instagram
    cmd = message.text.split()
    origem = cmd[1] if len(cmd) > 1 else "Direto"
    
    usuarios_coll.update_one(
        {"user_id": user_id},
        {"$set": {"origem": origem, "data_adesao": datetime.now()}},
        upsert=True
    )
    bot.send_message(message.chat.id, "🚀 **MestreFisio V6.2**\nGestão e Inteligência Clínica.", reply_markup=menu_principal(user_id))

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    
    if call.data == "config_perfil":
        msg = bot.send_message(call.message.chat.id, "✍️ Digite no formato:\n**Nome - Registro - Idade - Cidade/UF**")
        bot.register_next_step_handler(msg, processar_perfil)
    
    elif call.data == "novo_paciente":
        ok, perfil = verificar_registro(user_id, call.message.chat.id)
        if ok:
            pode, qtd = verificar_limite(user_id, perfil)
            if pode:
                msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
                bot.register_next_step_handler(msg, iniciar_laudo)
            else:
                bot.send_message(call.message.chat.id, "🚫 **Limite atingido (3/3)**. Assine o plano Premium.")

    elif call.data == "consulta_avulsa":
        ok, _ = verificar_registro(user_id, call.message.chat.id)
        if ok:
            msg = bot.send_message(call.message.chat.id, "💡 Qual sua dúvida técnica?")
            bot.register_next_step_handler(msg, processar_consulta)

    elif call.data == "painel_admin":
        if user_id == ADMIN_ID:
            u, p = usuarios_coll.count_documents({}), pacientes_coll.count_documents({})
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("📥 Exportar Planilha Marketing", callback_data="exportar_csv"))
            bot.send_message(call.message.chat.id, f"📊 **ADMIN:**\nUsuários: {u}\nLaudos: {p}", reply_markup=markup)

    elif call.data == "exportar_csv":
        exportar_dados(call.message)

# --- 7. PROCESSAMENTO ---
def processar_perfil(message):
    try:
        dados = [d.strip() for d in message.text.split("-")]
        nome, reg = dados[0], dados[1]
        idade = dados[2] if len(dados) > 2 else "N/A"
        local = dados[3] if len(dados) > 3 else "N/A"
        
        usuarios_coll.update_one({"user_id": message.from_user.id}, 
            {"$set": {"nome": nome, "registro": reg, "idade": idade, "local": local}}, upsert=True)
        bot.send_message(message.chat.id, "✅ Perfil salvo!", reply_markup=menu_principal(message.from_user.id))
    except:
        bot.send_message(message.chat.id, "❌ Use o formato correto com traços.")

def iniciar_laudo(message):
    nome_p = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: {nome_p}\nDescreva o quadro clínico:")
    bot.register_next_step_handler(msg, gerar_laudo_final, nome_p)

def gerar_laudo_final(message, nome_p):
    user_id = message.from_user.id
    aguarde = bot.send_message(message.chat.id, "🧠 Gerando análise PhD...")
    perfil = usuarios_coll.find_one({"user_id": user_id})
    
    prompt = f"Fisioterapeuta PhD. Analise o caso e gere um relatório de 15 tópicos: Paciente {nome_p}. {message.text}"
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=60)
        analise = res.json()['candidates'][0]['content']['parts'][0]['text']
        
        # SALVAR NO BANCO PRIMEIRO
        pacientes_coll.update_one({"user_id": user_id, "nome": nome_p}, {"$push": {"consultas": {"data": datetime.now(), "txt": analise}}}, upsert=True)
        usuarios_coll.update_one({"user_id": user_id}, {"$inc": {"laudos_usados": 1}})

        # PDF SEGURO
        path = f"Laudo_{nome_p.replace(' ', '_')}.pdf"
        pdf = PDF_Relatorio(perfil['nome'], perfil['registro'])
        pdf.add_page()
        pdf.set_font("Arial", size=11)
        # Remove emojis e caracteres não-latinos para o PDF não travar
        txt_pdf = analise.encode('ascii', 'ignore').decode('ascii')
        pdf.multi_cell(0, 8, txt_pdf)
        pdf.output(path)
        
        bot.delete_message(message.chat.id, aguarde.message_id)
        with open(path, "rb") as f: bot.send_document(message.chat.id, f)
        os.remove(path)
    except Exception as e:
        bot.send_message(message.chat.id, "❌ Erro ao gerar laudo. Tente novamente.")

def processar_consulta(message):
    aguarde = bot.send_message(message.chat.id, "🧠 Consultando...")
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
        res = requests.post(url, json={"contents": [{"parts": [{"text": f"Dúvida técnica fisio: {message.text}"}]}]})
        bot.send_message(message.chat.id, res.json()['candidates'][0]['content']['parts'][0]['text'])
    except:
        bot.send_message(message.chat.id, "❌ Erro na consulta.")

def exportar_dados(message):
    filename = "marketing_mestrefisio.csv"
    with open(filename, 'w', newline='', encoding='utf-16') as f:
        w = csv.writer(f, delimiter='\t')
        w.writerow(['Nome', 'Registro', 'Idade', 'Local', 'Origem', 'Uso'])
        for u in usuarios_coll.find({}):
            w.writerow([u.get('nome'), u.get('registro'), u.get('idade'), u.get('local'), u.get('origem'), u.get('laudos_usados')])
    with open(filename, 'rb') as f: bot.send_document(message.chat.id, f)
    os.remove(filename)

if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling()
