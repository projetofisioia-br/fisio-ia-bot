import telebot, requests, os
from telebot import types # Import necessário para os botões
from flask import Flask
from threading import Thread

app = Flask('')
@app.route('/')
def home(): return "MestreFisio Botões Online"

def run():
    app.run(host='0.0.0.0', port=10000)

TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-2.5-flash"

bot = telebot.TeleBot(TOKEN_TELEGRAM)

# --- FUNÇÃO PARA CRIAR O MENU DE BOTÕES ---
def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_paciente = types.InlineKeyboardButton("👤 Analisar Novo Paciente", callback_data="novo_paciente")
    btn_duvida = types.InlineKeyboardButton("📚 Dúvida Técnica Direta", callback_data="duvida_tecnica")
    markup.add(btn_paciente, btn_duvida)
    return markup

# --- COMANDO START ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    text = (
        "🚀 **MestreFisio IA Ativo!**\n\n"
        "Selecione uma opção abaixo para começar:"
    )
    bot.send_message(message.chat.id, text, reply_markup=menu_principal(), parse_mode="Markdown")

# --- TRATAMENTO DOS CLIQUES NOS BOTÕES ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Digite o **NOME** do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
    
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 O que você deseja saber? Digite sua dúvida:")
        bot.register_next_step_handler(msg, processar_ia_direta)

# --- FLUXO DE PACIENTE ---
def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: **{nome}**\n\nAgora, descreva o quadro clínico ou queixa:")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):
    prompt = (f"Atue como um fisioterapeuta PhD. Analise o caso do paciente {nome}: {message.text}. "
              "Estruture em: Hipóteses, Testes Sugeridos e Conduta.")
    chamar_gemini(message, prompt)

# --- FLUXO DE DÚVIDA DIRETA ---
def processar_ia_direta(message):
    prompt = f"Atue como um fisioterapeuta PhD. Responda de forma técnica e objetiva: {message.text}"
    chamar_gemini(message, prompt)

# --- MOTOR DA IA ---
def chamar_gemini(message, prompt):
    aguarde = bot.send_message(message.chat.id, "🧠 Consultando base científica...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        response = requests.post(url, json=payload, timeout=60)
        res_data = response.json()
        analise = res_data['candidates'][0]['content']['parts'][0]['text']
        
        bot.delete_message(message.chat.id, aguarde.message_id)
        
        # Envia a resposta
        if len(analise) > 4000:
            for i in range(0, len(analise), 4000):
                bot.send_message(message.chat.id, analise[i:i+4000])
        else:
            bot.send_message(message.chat.id, analise)
        
        # FINALIZA MOSTRANDO O MENU NOVAMENTE
        bot.send_message(message.chat.id, "O que deseja fazer agora?", reply_markup=menu_principal())
            
    except Exception as e:
        bot.send_message(message.chat.id, "❌ Erro na IA. Tente novamente.", reply_markup=menu_principal())

if __name__ == "__main__":
    t = Thread(target=run)
    t.daemon = True
    t.start()
    bot.remove_webhook()
    print("🤖 Bot com botões iniciado!")
    bot.infinity_polling()
