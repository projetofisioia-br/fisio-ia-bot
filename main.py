import telebot, requests, os
from flask import Flask
from threading import Thread

# --- SERVIDOR PARA MANTER O RENDER ATIVO ---
app = Flask('')
@app.route('/')
def home(): return "Servidor Ativo"

def run():
    # O Render usa a porta 10000 por padrão no plano Free
    app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES SEGURAS ---
# O Token do Telegram pode ficar aqui, mas a API KEY vai para o ambiente
TOKEN_TELEGRAM = "8725541698:AAEZY9yQPAumO6E7P7NHIAFWx7F9fAveUSk"
API_KEY_IA = os.environ.get("API_KEY_IA") # Puxa do Render
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
    queixa = message.text
    bot.send_message(message.chat.id, "🧠 Analisando... por favor aguarde.")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    payload = {
        "contents": [{"parts": [{"text": f"Atue como fisioterapeuta especialista. Analise o caso de {nome}: {queixa}"}]}]
    }
    
    try:
        response = requests.post(url, json=payload, timeout=60)
        res_data = response.json()
        
        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            bot.send_message(message.chat.id, analise)
        else:
            bot.send_message(message.chat.id, "⚠️ Erro: A IA não respondeu. Verifique se a chave no Render está correta.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro de conexão: {e}")

if __name__ == "__main__":
    t = Thread(target=run)
    t.daemon = True
    t.start()
    
    # Limpa webhooks antigos para evitar o erro 409 Conflict
    bot.remove_webhook()
    print("🤖 Bot iniciado!")
    bot.infinity_polling()
    
