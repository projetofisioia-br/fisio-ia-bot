import telebot, requests, os
from flask import Flask
from threading import Thread

# --- SERVIDOR PARA O RENDER ---
app = Flask('')
@app.route('/')
def home(): 
    return "MestreFisio com Gemini 2.5 Online"

def run():
    # Porta padrão para o plano gratuito do Render
    app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES VIA AMBIENTE ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")

# DEFINIÇÃO DO MODELO (ESCOLHIDO COM BASE NA SUA LISTA)
MODELO = "gemini-2.5-flash"

bot = telebot.TeleBot(TOKEN_TELEGRAM)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "🚀 AGENTE FISIO ATIVO!\nUtilizando inteligência Gemini 2.5 Flash.\n\nDigite o **NOME DO PACIENTE** para começar.")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    nome = message.text.upper().strip()
    bot.send_message(message.chat.id, f"👤 Paciente: {nome}\nDescreva o quadro clínico completo:")
    bot.register_next_step_handler(message, processar_ia, nome)

def processar_ia(message, nome):
    queixa = message.text
    # Mensagem de feedback para o usuário
    aguarde = bot.send_message(message.chat.id, "🧠 Processando análise clínica... Por favor, aguarde.")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    headers = {'Content-Type': 'application/json'}
    
    # Prompt otimizado para a área de Fisioterapia
    payload = {
        "contents": [{
            "parts": [{
                "text": (f"Atue como um fisioterapeuta PhD. Analise o caso de {nome}: {queixa}. "
                        "Estruture sua resposta com: 1. Hipóteses Diagnósticas, "
                        "2. Testes Ortopédicos sugeridos, 3. Conduta Fisioterapêutica imediata.")
            }]
        }]
    }
    
    try:
        # Timeout de 60s para garantir que o Render não derrube a conexão
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        res_data = response.json()
        
        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            
            # Remove a mensagem de "aguarde" antes de enviar a resposta final
            bot.delete_message(message.chat.id, aguarde.message_id)

            # Envio da resposta (trata mensagens maiores que 4000 caracteres)
            if len(analise) > 4000:
                for i in range(0, len(analise), 4000):
                    bot.send_message(message.chat.id, analise[i:i+4000])
            else:
                bot.send_message(message.chat.id, analise)
        else:
            bot.edit_message_text("⚠️ A IA não conseguiu gerar a resposta. Verifique a API Key no Render.", 
                                 message.chat.id, aguarde.message_id)
            print(f"Erro detalhado: {res_data}")

    except Exception as e:
        bot.edit_message_text(f"❌ Erro de conexão ou tempo esgotado. Tente novamente.", 
                             message.chat.id, aguarde.message_id)
        print(f"Erro: {e}")

if __name__ == "__main__":
    t = Thread(target=run)
    t.daemon = True
    t.start()
    
    # Limpa webhooks para evitar erro 409
    bot.remove_webhook()
    print(f"🤖 Bot iniciado com {MODELO}!")
    bot.infinity_polling(timeout=60, long_polling_timeout=30)
