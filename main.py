import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from fpdf import FPDF

# --- 1. CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# SERVIDOR WEB PARA O RENDER
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V9.1 Online"
def run(): app.run(host='0.0.0.0', port=10000)

# --- 2. FUNÇÃO DA IA (CONEXÃO ESTÁVEL) ---
def chamar_ai(prompt):
    # Usando v1 para garantir compatibilidade com contas Free/Pro
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={API_KEY_IA}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        res = requests.post(url, json=payload, timeout=25)
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    except:
        return "⚠️ O servidor PhD está processando muitas requisições. Tente novamente em breve."

# --- 3. MENUS E INTERFACE ---
def menu_inicial():
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(
        types.InlineKeyboardButton("📄 Gerar Laudo PhD (PDF)", callback_data="laudo"),
        types.InlineKeyboardButton("💡 Consulta Técnica PhD", callback_data="consulta"),
        types.InlineKeyboardButton("💎 Assinar Planos Pro", callback_data="menu_planos")
    )
    return m

def menu_assinaturas():
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(
        types.InlineKeyboardButton("🥈 Plano Mensal - R$ 49,90", callback_data="pix_mensal"),
        types.InlineKeyboardButton("🥇 Plano Anual (Promo) - R$ 399,00", callback_data="pix_anual"),
        types.InlineKeyboardButton("⬅️ Voltar", callback_data="voltar")
    )
    return m

# --- 4. HANDLERS (COMANDOS) ---
@bot.message_handler(commands=['start'])
def boas_vindas(m):
    bot.send_message(m.chat.id, "✨ **MestreFisio PhD**\nSeu assistente clínico oficial.", reply_markup=menu_inicial())

@bot.callback_query_handler(func=lambda call: True)
def tratar_botoes(call):
    if call.data == "laudo":
        msg = bot.send_message(call.message.chat.id, "📝 Digite o **NOME** do paciente:")
        bot.register_next_step_handler(msg, laudo_passo_final)
    
    elif call.data == "consulta":
        msg = bot.send_message(call.message.chat.id, "💡 Descreva o caso clínico ou dúvida técnica:")
        bot.register_next_step_handler(msg, responder_consulta)
    
    elif call.data == "menu_planos":
        bot.edit_message_text("💎 **ESCOLHA SEU PLANO PRO**\n\nLibere laudos ilimitados e análise de exames.", 
                              call.message.chat.id, call.message.message_id, reply_markup=menu_assinaturas())

    elif call.data == "pix_mensal":
        texto = (
            "🥈 **PLANO MENSAL PRO**\n\n"
            "💰 Valor: **R$ 49,90/mês**\n"
            "🔑 Chave PIX (E-mail): `projetofisioia-br@gmail.com`\n\n"
            "Após o pagamento, envie o comprovante para o suporte."
        )
        bot.send_message(call.message.chat.id, texto, parse_mode="Markdown")

    elif call.data == "pix_anual":
        texto = (
            "🥇 **PLANO ANUAL PRO (Economia de 33%)**\n\n"
            "💰 Valor: **R$ 399,00/ano**\n"
            "🔑 Chave PIX (E-mail): `projetofisioia-br@gmail.com`\n\n"
            "Após o pagamento, envie o comprovante para o suporte."
        )
        bot.send_message(call.message.chat.id, texto, parse_mode="Markdown")
    
    elif call.data == "voltar":
        bot.edit_message_text("✨ Escolha uma opção:", call.message.chat.id, call.message.message_id, reply_markup=menu_inicial())

# --- 5. LÓGICA DE NEGÓCIO ---
def responder_consulta(m):
    status = bot.send_message(m.chat.id, "🧠 Consultando base PhD...")
    resposta = chamar_ai(f"Responda como Fisioterapeuta PhD de forma técnica: {m.text}")
    bot.edit_message_text(f"💡 **Parecer Técnico:**\n\n{resposta}", m.chat.id, status.message_id)

def laudo_passo_final(m):
    nome_p = m.text.upper()
    msg = bot.send_message(m.chat.id, f"✅ Paciente: {nome_p}\nAgora descreva o quadro clínico:")
    bot.register_next_step_handler(msg, finalizar_laudo_pdf, nome_p)

def finalizar_laudo_pdf(m, nome):
    status = bot.send_message(m.chat.id, "⏳ Gerando documento PDF...")
    prompt = f"Gere um laudo fisioterapêutico formal e PhD para o paciente {nome}: {m.text}"
    conteudo = chamar_ai(prompt)
    
    path = f"Laudo_{nome}.pdf"
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=11)
        pdf.multi_cell(0, 10, conteudo.encode('latin-1', 'replace').decode('latin-1'))
        pdf.output(path)
        
        with open(path, "rb") as f:
            bot.send_document(m.chat.id, f, caption=f"📄 Laudo de {nome}")
        os.remove(path)
    except:
        bot.send_message(m.chat.id, "❌ Erro ao converter laudo para PDF.")
    
    bot.delete_message(m.chat.id, status.message_id)

# --- 6. EXECUÇÃO ---
if __name__ == "__main__":
    # Remove webhook para evitar erro 409
    bot.remove_webhook()
    Thread(target=run).start()
    bot.infinity_polling(timeout=60)
