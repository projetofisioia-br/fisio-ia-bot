import telebot, requests, os
from flask import Flask
from threading import Thread

# Servidor básico para o Render não derrubar o bot
app = Flask('')
@app.route('/')
def home(): return "Bot Online"

def run():
    app.run(host='0.0.0.0', port=10000)

# Busca as chaves configuradas no menu "Ambiente" do Render
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemma-3-27b-it"

bot = telebot.TeleBot(TOKEN_TELEGRAM)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "🚀 AGENTE FISIO ATIVO!\nDigite o NOME DO PACIENTE.")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    nome = message.text.upper().strip()
    bot.send_message(message.chat.id, f"👤 Paciente: {nome}\nDescreva o quadro clínico:")
    bot.register_next_step_handler(message, processar_ia, nome)

def processar_ia(message, nome):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    payload = {"contents": [{"parts": [{"text": f"Avaliação fisioterapêutica para {nome}: {message.text}"}]}]}
    try:
        bot.send_message(message.chat.id, "🧠 Analisando...")
        res = requests.post(url, json=payload, timeout=30).json()
        if 'candidates' in res:
            analise = res['candidates'][0]['content']['parts'][0]['text']
            bot.send_message(message.chat.id, analise)
        else:
            bot.send_message(message.chat.id, "⚠️ Erro na resposta da IA. Verifique a API Key.")
    except Exception as e:
        bot.send_message(message.chat.id, "❌ Erro de conexão.")

if __name__ == "__main__":
    t = Thread(target=run)
    t.daemon = True
    t.start()
    
    # Remove qualquer conexão antiga para evitar erro 409
    bot.remove_webhook()
    print("🤖 Bot iniciado com sucesso!")
    bot.infinity_polling()
    
