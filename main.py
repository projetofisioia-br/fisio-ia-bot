import telebot, requests, os
from flask import Flask
from threading import Thread

# --- SERVIDOR PARA O RENDER ---
app = Flask('')
@app.route('/')
def home(): 
    return "Bot MestreFisio Online"

def run():
    # Porta 10000 é obrigatória para o plano Free do Render
    app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES VIA VARIÁVEIS DE AMBIENTE ---
# Lembre-se de configurar TOKEN_TELEGRAM e API_KEY_IA no menu Environment do Render
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")

# Modelo mais estável para evitar erros de permissão
MODELO = "gemini-1.5-flash" 

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
    bot.send_message(message.chat.id, "🧠 Analisando clinicamente... Por favor, aguarde.")
    
    # URL formatada para a API do Google Gemini
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    # Cabeçalhos para garantir a conexão estável
    headers = {'Content-Type': 'application/json'}
    
    # Prompt estruturado para análise fisioterapêutica
    payload = {
        "contents": [{
            "parts": [{
                "text": f"Atue como um fisioterapeuta experiente. Analise o caso de {nome}: {queixa}. "
                        f"Forneça hipóteses diagnósticas e sugestões de conduta."
            }]
        }]
    }
    
    try:
        # Requisição para a IA com timeout de 60 segundos
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        res_data = response.json()
        
        # Verifica se a IA retornou conteúdo válido
        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            
            # Divide a mensagem se for maior que o limite do Telegram (4096 caracteres)
            if len(analise) > 4000:
                for i in range(0, len(analise), 4000):
                    bot.send_message(message.chat.id, analise[i:i+4000])
            else:
                bot.send_message(message.chat.id, analise)
        else:
            # Caso a API retorne erro de chave ou limite
            bot.send_message(message.chat.id, "⚠️ A IA não conseguiu gerar resposta. Verifique a API Key no Render.")
            print(f"Erro da API: {res_data}") # Log para conferir no painel do Render

    except Exception as e:
        bot.send_message(message.chat.id, "❌ Erro de conexão com o servidor de IA.")
        print(f"Erro de conexão: {e}")

if __name__ == "__main__":
    # Inicia o servidor Flask em uma thread separada
    t = Thread(target=run)
    t.daemon = True
    t.start()
    
    # Limpa webhooks antigos para evitar Erro 409 (Conflito)
    bot.remove_webhook()
    print("🤖 Bot iniciado com sucesso!")
    
    # Mantém o bot rodando e reconecta em caso de quedas simples
    bot.infinity_polling(timeout=60, long_polling_timeout=30)
