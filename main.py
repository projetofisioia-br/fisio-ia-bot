import telebot, sqlite3, requests, os
from flask import Flask
from threading import Thread

# --- MINI SERVER PARA O RENDER NÃO DERRUBAR ---
app = Flask('')
@app.route('/')
def home(): return "Servidor Ativo"
def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8736702883:AAHL4lTqfqR7eW2QGa5vFsYvKWNkgeoEjXw"
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
    payload = {"contents": [{"parts": [{"text": f"Avaliação técnica fisioterapêutica para {nome}: {message.text}"}]}]}
    try:
        bot.send_message(message.chat.id, "🧠 Processando análise clínica...")
        res = requests.post(url, json=payload, timeout=60).json()
        analise = res['candidates'][0]['content']['parts'][0]['text']
        bot.send_message(message.chat.id, analise)
    except Exception as e:
        bot.send_message(message.chat.id, "⚠️ Erro na IA. Verifique se a chave API no Render está correta.")

if __name__ == "__main__":
    t = Thread(target=run)
    t.start()
    print("🤖 Bot Iniciado!")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
