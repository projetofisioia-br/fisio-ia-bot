import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V4.6 - Sistema de Resposta Longa Estabilizado"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-2.5-flash"

# threaded=False evita o erro 409 de conflito que vimos nos logs anteriores
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# SEU PROMPT ULTRA-AVANÇADO (Resumo para o sistema)
PROMPT_SISTEMA = """
Você é um Fisioterapeuta PhD. Forneça uma análise técnica estruturada em 15 tópicos (Definição, Anatomia, Biomecânica, Etiologia, Sintomas, Raciocínio, Avaliação, Testes, Diagnóstico Diferencial, Exames, Classificação, Conduta, Protocolo Atleta, Algoritmo e Red Flags).
Use linguagem técnica avançada e formatação Markdown.
"""

def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_paciente = types.InlineKeyboardButton("👤 Novo Paciente", callback_data="novo_paciente")
    btn_duvida = types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica")
    markup.add(btn_paciente, btn_duvida)
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "🚀 **MestreFisio V4.6 Especialista**\nPronto para análises de alta complexidade.", reply_markup=menu_principal())

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual condição deseja analisar?")
        bot.register_next_step_handler(msg, processar_ia_direta)

def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: **{nome}**\nDescreva o quadro:")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):
    prompt = f"{PROMPT_SISTEMA}\n\nAnalise o caso de {nome}: {message.text}"
    chamar_gemini(message, prompt)

def processar_ia_direta(message):
    prompt = f"{PROMPT_SISTEMA}\n\nExplique tecnicamente: {message.text}"
    chamar_gemini(message, prompt)

def chamar_gemini(message, prompt):
    aguarde = bot.send_message(message.chat.id, "🧠 **Gerando análise PhD...**\nIsso pode levar até 60s devido à profundidade do relatório.")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    try:
        # Timeout estendido para 300 segundos para evitar queda de conexão
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=300)
        res_data = response.json()
        
        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            bot.delete_message(message.chat.id, aguarde.message_id)
            
            # Divisão em blocos menores (2000 carac) para garantir entrega sem erro de conexão
            partes = [analise[i:i+2000] for i in range(0, len(analise), 2000)]
            for p in partes:
                bot.send_message(message.chat.id, p, parse_mode="Markdown")
                time.sleep(0.8) # Pausa para o Telegram processar o volume de dados
            
            bot.send_message(message.chat.id, "✅ **Relatório Finalizado.**", reply_markup=menu_principal())
        else:
            bot.send_message(message.chat.id, "⚠️ Erro na geração. Tente ser mais específico.")

    except Exception as e:
        bot.send_message(message.chat.id, "❌ Conexão instável. Tente novamente em alguns segundos.")

if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    time.sleep(2)
    bot.infinity_polling(timeout=90, long_polling_timeout=30)
