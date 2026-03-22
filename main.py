import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient
from fpdf import FPDF

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V6.5 - PDF & Histórico Ativo"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "").strip()
API_KEY_IA = os.environ.get("API_KEY_IA", "").strip()
MONGO_URI = os.environ.get("MONGO_URI", "").strip()
TOKEN_PAYMENT = os.environ.get("TOKEN_PAYMENT", "").strip()

MODELO = "gemini-1.5-flash"
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
usuarios_coll = db['usuarios']
pacientes_coll = db['pacientes']

PROMPT_SISTEMA = "Atue como um Fisioterapeuta PhD. Forneça análise em 15 tópicos técnicos focados em excelência clínica."

# --- CLASSE PARA GERAR PDF ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'RELATÓRIO DE EVOLUÇÃO FISIOTERAPÊUTICA - HOME CARE', 0, 1, 'C')
        self.ln(5)

# --- MENUS ---
def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👤 Novo Paciente", callback_data="novo_paciente"),
        types.InlineKeyboardButton("📂 Histórico e Gerar PDF", callback_data="ver_historico"),
        types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica"),
        types.InlineKeyboardButton("💎 Planos de Acesso Pro", callback_data="planos")
    )
    return markup

# --- LÓGICA DE PDF ---
def gerar_pdf_homecare(user_id, nome_paciente, analise_texto):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=11)
    
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(0, 10, f"Paciente: {nome_paciente}", 1, 1, 'L', 1)
    pdf.cell(0, 10, f"Data: {time.strftime('%d/%m/%Y')}", 1, 1, 'L')
    pdf.ln(10)
    
    # Limpa caracteres que o FPDF não suporta (Markdown)
    texto_limpo = analise_texto.replace("**", "").replace("#", "")
    pdf.multi_cell(0, 10, texto_limpo)
    
    path = f"Relatorio_{nome_paciente}.pdf"
    pdf.output(path)
    return path

# --- LÓGICA DE PAGAMENTO (STAY STABLE) ---
@bot.callback_query_handler(func=lambda call: call.data == "planos")
def enviar_fatura(call):
    try:
        bot.send_invoice(
            call.message.chat.id, "MestreFisio PhD Pro 💎", "Acesso ilimitado e PDFs ilimitados.",
            TOKEN_PAYMENT, "BRL", [types.LabeledPrice("Assinatura Mensal", 5990)],
            invoice_payload="pro_access_payload", start_parameter="mestre-fisio-pro"
        )
    except Exception as e: bot.send_message(call.message.chat.id, f"⚠️ Erro no pagamento: {e}")

# --- IA E HISTÓRICO ---
def chamar_ia(message, texto_usuario, nome_paciente=None):
    user_id = message.from_user.id
    user_data = usuarios_coll.find_one({"user_id": user_id}) or {"plano": "FREE", "consultas": 0}
    
    if user_data.get("plano") != "PRO" and user_data.get("consultas", 0) >= 3:
        bot.send_message(message.chat.id, "⚠️ Limite atingido! Assine o Pro para gerar PDFs e continuar.", reply_markup=menu_principal())
        return

    aguarde = bot.send_message(message.chat.id, "🧠 **Gerando raciocínio clínico PhD...**")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    try:
        payload = {"contents": [{"parts": [{"text": f"{PROMPT_SISTEMA}\n\nCASO: {texto_usuario}"}]}]}
        response = requests.post(url, json=payload, timeout=60)
        res_data = response.json()
        
        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            bot.delete_message(message.chat.id, aguarde.message_id)
            
            # Salva no Histórico
            if nome_paciente:
                pacientes_coll.update_one(
                    {"profissional_id": user_id, "nome": nome_paciente},
                    {"$set": {"ultima_analise": analise, "data": time.strftime("%d/%m/%Y")}}, upsert=True
                )
            
            usuarios_coll.update_one({"user_id": user_id}, {"$inc": {"consultas": 1}}, upsert=True)
            
            for parte in [analise[i:i+4000] for i in range(0, len(analise), 4000)]:
                bot.send_message(message.chat.id, parte, parse_mode="Markdown")

            # Se for Pro, oferece gerar PDF
            if user_data.get("plano") == "PRO" and nome_paciente:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("📄 Gerar PDF Home Care", callback_data=f"pdf_{nome_paciente}"))
                bot.send_message(message.chat.id, "✨ Análise pronta! Deseja gerar o documento para o paciente?", reply_markup=markup)
        else:
            bot.send_message(message.chat.id, "⚠️ Erro na IA.")
    except: bot.send_message(message.chat.id, "❌ Falha técnica.")

# --- HANDLERS ---
@bot.callback_query_handler(func=lambda call: True)
def callback_geral(call):
    user_id = call.from_user.id
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do Paciente:")
        bot.register_next_step_handler(msg, lambda m: bot.register_next_step_handler(
            bot.send_message(m.chat.id, f"✅ Paciente: {m.text.upper()}\nDescreva o quadro:"), 
            lambda m2: chamar_ia(m2, m2.text, m.text.upper())))
    
    elif call.data.startswith("pdf_"):
        nome_p = call.data.split("_")[1]
        p_data = pacientes_coll.find_one({"profissional_id": user_id, "nome": nome_p})
        if p_data:
            path = gerar_pdf_homecare(user_id, nome_p, p_data['ultima_analise'])
            with open(path, 'rb') as f:
                bot.send_document(call.message.chat.id, f, caption=f"📄 Relatório Home Care - {nome_p}")
            os.remove(path)
            
    elif call.data == "ver_historico":
        pacientes = list(pacientes_coll.find({"profissional_id": user_id}))
        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Nenhum paciente no seu histórico.")
        else:
            markup = types.InlineKeyboardMarkup()
            for p in pacientes:
                markup.add(types.InlineKeyboardButton(f"👤 {p['nome']}", callback_data=f"pdf_{p['nome']}"))
            bot.send_message(call.message.chat.id, "📂 Selecione o paciente para gerar o PDF:", reply_markup=markup)
    
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual a sua dúvida?")
        bot.register_next_step_handler(msg, lambda m: chamar_ia(m, m.text))
        
    bot.answer_callback_query(call.id)

@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "🚀 **MestreFisio PhD**\nGestão e Inteligência Clínica.", reply_markup=menu_principal())

if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    bot.infinity_polling(timeout=120)
