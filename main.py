import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread

# --- CONFIGURAÇÃO DO SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): 
    return "MestreFisio Ativo e Alerta - Sistema Anti-Sono OK"

def run():
    app.run(host='0.0.0.0', port=10000)

# --- O TRUQUE: FUNÇÃO ANTI-SONO ---
def keep_alive():
    url_do_seu_bot = "https://fisio-ia-bot.onrender.com" 
    while True:
        try:
            # Faz uma requisição para si mesmo para impedir o Render de hibernar
            requests.get(url_do_seu_bot)
            print("⚓ Ping preventivo enviado: Servidor mantido acordado!")
        except Exception as e:
            print(f"⚠️ Falha no ping preventivo: {e}")
        
        # Espera 10 minutos (600 segundos) para o próximo ping
        time.sleep(600)

# --- CONFIGURAÇÕES DO BOT ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-2.5-flash"

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=True)

# Menu de Botões
def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_paciente = types.InlineKeyboardButton("👤 Analisar Novo Paciente", callback_data="novo_paciente")
    btn_duvida = types.InlineKeyboardButton("📚 Dúvida Técnica Direta", callback_data="duvida_tecnica")
    markup.add(btn_paciente, btn_duvida)
    return markup

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.send_message(
        message.chat.id, 
        "🚀 **MestreFisio IA Ativo!**\nSua inteligência clínica avançada.\n\nEscolha uma opção abaixo:", 
        reply_markup=menu_principal(), 
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Digite o **NOME** do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Digite sua dúvida técnica (ex: exercícios para manguito):")
        bot.register_next_step_handler(msg, processar_ia_direta)

def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: **{nome}**\n\nAgora, descreva o quadro clínico ou queixa:")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):
    prompt = (f"Atue como um fisioterapeuta PhD. Analise o caso de {nome}: {message.text}. "
              "Estruture em: 1. Hipóteses Diagnósticas, 2. Testes Sugeridos, 3. Conduta Imediata.")
    chamar_gemini(message, prompt)

def processar_ia_direta(message):
    prompt = f"Responda como um fisioterapeuta PhD de forma técnica, clara e baseada em evidências: {message.text}"
    chamar_gemini(message, prompt)

def chamar_gemini(message, prompt):
    aguarde = bot.send_message(message.chat.id, "🧠 Consultando base científica...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=60)
        res_json = response.json()
        analise = res_json['candidates'][0]['content']['parts'][0]['text']
        
        bot.delete_message(message.chat.id, aguarde.message_id)
        
        if len(analise) > 4000:
            for i in range(0, len(analise), 4000):
                bot.send_message(message.chat.id, analise[i:i+4000])
        else:
            bot.send_message(message.chat.id, analise)
        
        bot.send_message(message.chat.id, "O que deseja fazer agora?", reply_markup=menu_principal())
            
    except Exception as e:
        bot.send_message(message.chat.id, "❌ Erro na IA ou tempo esgotado. Tente novamente.", reply_markup=menu_principal())
        print(f"Erro: {e}")

if __name__ == "__main__":
    # Inicia o servidor Flask
    Thread(target=run).start()
    # Inicia o sistema Anti-Sono
    Thread(target=keep_alive).start()
    
    bot.remove_webhook()
    print("🤖 MestreFisio ON e Sistema Anti-Sono Ativado!")
    bot.infinity_polling(timeout=20, long_polling_timeout=5)
