import telebot, requests, os
from flask import Flask
from threading import Thread

# --- SERVIDOR PARA MANTER O RENDER ATIVO ---
app = Flask('')
@app.route('/')
def home(): 
    return "Agente Fisio 2026 - Online"

def run():
    # O Render exige a porta 10000 no plano gratuito
    app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES SEGURAS (PUXANDO DO RENDER) ---
# No GitHub, deixamos apenas o comando para ler do servidor
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemma-3-27b-it"

bot = telebot.TeleBot(TOKEN_TELEGRAM)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "🚀 AGENTE FISIO ATIVO!\nDigite o NOME DO PACIENTE para iniciar a análise.")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    nome = message.text.upper().strip()
    bot.send_message(message.chat.id, f"👤 Paciente: {nome}\nDescreva o quadro clínico atual:")
    bot.register_next_step_handler(message, processar_ia, nome)

def processar_ia(message, nome):
    queixa = message.text
    bot.send_message(message.chat.id, "🧠 Analisando clinicamente... Aguarde.")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    payload = {
        "contents": [{"parts": [{"text": f"Atue como um fisioterapeuta experiente. Analise o caso de {nome}: {queixa}"}]}]
    }
    
    try:
        response = requests.post(url, json=payload, timeout=60)
        res_data = response.json()
        
        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            # Envia a resposta dividida se for muito longa para o Telegram
            if len(analise) > 4000:
                for i in range(0, len(analise), 4000):
                    bot.send_message(message.chat.id, analise[i:i+4000])
            else:
                bot.send_message(message.chat.id, analise)
        else:
            bot.send_message(message.chat.id, "⚠️ A IA não conseguiu gerar a análise. Verifique se a API Key no Render está correta.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro de conexão: {e}")

if __name__ == "__main__":
    # Inicia servidor Flask em segundo plano
    t = Thread(target=run)
    t.daemon = True
    t.start()
    
    # Limpa conexões antigas (Evita erro 409 Conflict)
    bot.remove_webhook()
    print("🤖 Bot iniciado com sucesso!")
    bot.infinity_polling()
