import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V4.5 - Estabilidade de Respostas Longas"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-2.5-flash"

# threaded=False é crucial para evitar o Erro 409 de conflito no Render
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# SEU PROMPT ULTRA-AVANÇADO
PROMPT_SISTEMA = """
Você é um assistente clínico altamente especializado em fisioterapia.
Siga rigorosamente os 15 tópicos da estrutura padrão enviada anteriormente.
Seja técnico, profundo e use linguagem de nível PhD.
"""

def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_paciente = types.InlineKeyboardButton("👤 Analisar Novo Paciente", callback_data="novo_paciente")
    btn_duvida = types.InlineKeyboardButton("📚 Dúvida Técnica Direta", callback_data="duvida_tecnica")
    markup.add(btn_paciente, btn_duvida)
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "🚀 **MestreFisio V4.5 - Modo Especialista**\nPronto para análises de alta complexidade.", reply_markup=menu_principal())

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Digite o **NOME** do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual condição deseja analisar?")
        bot.register_next_step_handler(msg, processar_ia_direta)

def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: **{nome}**\nDescreva o quadro clínico:")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):
    prompt = f"{PROMPT_SISTEMA}\n\nAnalise o caso de {nome}: {message.text}"
    chamar_gemini(message, prompt)

def processar_ia_direta(message):
    prompt = f"{PROMPT_SISTEMA}\n\nExplique tecnicamente: {message.text}"
    chamar_gemini(message, prompt)

def chamar_gemini(message, prompt):
    aguarde = bot.send_message(message.chat.id, "🧠 Gerando análise clínica detalhada...\n*(Este processo é minucioso e pode levar até 1 minuto)*")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    try:
        # Aumentamos o timeout para 300 segundos (5 minutos)
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=300)
        res_data = response.json()
        
        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            bot.delete_message(message.chat.id, aguarde.message_id)
            
            # Divisão ultra-segura: o Telegram tem limite de caracteres e de mensagens por segundo
            # Vamos enviar em blocos menores de 3000 caracteres com pequena pausa
            for i in range(0, len(analise), 3000):
                bot.send_message(message.chat.id, analise[i:i+3000], parse_mode="Markdown")
                time.sleep(0.5) 
            
            bot.send_message(message.chat.id, "✅ Análise concluída.", reply_markup=menu_principal())
        else:
            bot.send_message(message.chat.id, "⚠️ A IA não conseguiu completar o raciocínio. Tente simplificar o pedido.")

    except requests.exceptions.Timeout:
        bot.send_message(message.chat.id, "❌ O servidor demorou muito para responder. Tente novamente em instantes.")
    except Exception as e:
        bot.send_message(message.chat.id, "❌ Falha na conexão técnica.")

if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    time.sleep(2)
    # Infinity polling ajustado para conexões instáveis
    bot.infinity_polling(timeout=120, long_polling_timeout=60)
