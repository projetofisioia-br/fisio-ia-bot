import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V4.4 - Ultra-Avançado Estabilizado"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-2.5-flash"

# threaded=False ajuda a evitar o erro 409 de conflito em servidores como o Render
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# INTEGRANDO SEU PROMPT ULTRA-AVANÇADO
PROMPT_SISTEMA = """
Você é um assistente clínico altamente especializado em fisioterapia musculoesquelética, ortopedia e medicina esportiva.
ESTRUTURA OBRIGATÓRIA DA RESPOSTA:
1. Definição clínica
2. Anatomia e biomecânica envolvida
3. Etiologia / causas mais comuns
4. Sinais e sintomas característicos
5. Raciocínio clínico inicial
6. Avaliação clínica passo a passo (Anamnese, Inspeção, Palpação, Funcional)
7. Testes clínicos ortopédicos relevantes (Nome, objetivo, técnica, positivo, interpretação)
8. Diagnósticos diferenciais
9. Exames complementares
10. Classificação da lesão (quando existir)
11. Conduta fisioterapêutica baseada em evidência (Fase aguda, intermediária, avançada)
12. Protocolos utilizados em atletas
13. Algoritmo de decisão clínica
14. Red flags (sinais de alerta)
15. Evidência científica

Use subtítulos claros, listas organizadas e linguagem técnica de nível pós-graduação.
"""

def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_paciente = types.InlineKeyboardButton("👤 Analisar Novo Paciente", callback_data="novo_paciente")
    btn_duvida = types.InlineKeyboardButton("📚 Dúvida Técnica Direta", callback_data="duvida_tecnica")
    markup.add(btn_paciente, btn_duvida)
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "🚀 **MestreFisio V4.4 Ativo**\nSistema de raciocínio clínico ultra-avançado.", reply_markup=menu_principal())

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Digite o **NOME** do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Digite a condição para análise técnica:")
        bot.register_next_step_handler(msg, processar_ia_direta)

def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: **{nome}**\nDescreva o quadro clínico completo:")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):
    prompt_final = f"{PROMPT_SISTEMA}\n\nCASO CLÍNICO DO PACIENTE {nome}:\n{message.text}"
    chamar_gemini(message, prompt_final)

def processar_ia_direta(message):
    prompt_final = f"{PROMPT_SISTEMA}\n\nDÚVIDA TÉCNICA:\n{message.text}"
    chamar_gemini(message, prompt_final)

def chamar_gemini(message, prompt):
    aguarde = bot.send_message(message.chat.id, "🧠 Analisando sob perspectiva PhD... (Aguarde a estruturação completa)")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=120)
        analise = response.json()['candidates'][0]['content']['parts'][0]['text']
        bot.delete_message(message.chat.id, aguarde.message_id)
        
        # O Telegram corta mensagens acima de 4096 caracteres. 
        # Como o novo prompt é profundo, o bot divide a resposta em blocos.
        if len(analise) > 4000:
            for i in range(0, len(analise), 4000):
                bot.send_message(message.chat.id, analise[i:i+4000], parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, analise, parse_mode="Markdown")
        
        bot.send_message(message.chat.id, "O que deseja fazer agora?", reply_markup=menu_principal())
            
    except Exception as e:
        bot.send_message(message.chat.id, "❌ Tempo de resposta excedido ou erro na IA. Tente reenviar em alguns instantes.")

if __name__ == "__main__":
    Thread(target=run).start()
    
    # Limpeza agressiva para evitar o erro 409 mostrado nos logs
    bot.remove_webhook()
    time.sleep(2)
    
    print("🤖 MestreFisio V4.4 ON!")
    bot.infinity_polling(timeout=90, long_polling_timeout=30)
