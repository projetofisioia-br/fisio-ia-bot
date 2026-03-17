import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V4.2 - Especialista PhD Ativo"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-2.5-flash"
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=True)

# SEU PROMPT ULTRA-AVANÇADO INTEGRADO
PROMPT_SISTEMA = """
Você é um assistente clínico altamente especializado em fisioterapia musculoesquelética, ortopedia e medicina esportiva. 
ESTRUTURA PADRÃO OBRIGATÓRIA (Siga exatamente):
1. Definição clínica
2. Anatomia e biomecânica (inclua músculos, ligamentos e impacto funcional)
3. Etiologia / causas (Traumáticas, Degenerativas, Sobrecarga, etc.)
4. Sinais e sintomas
5. Raciocínio clínico inicial
6. Avaliação clínica passo a passo (Anamnese, Inspeção, Palpação, Funcional)
7. Testes clínicos ortopédicos (Nome, Objetivo, Técnica, Resultado Positivo)
8. Diagnósticos diferenciais
9. Exames complementares (RX, USG, RM, etc.)
10. Classificação da lesão (Graus e critérios)
11. Conduta baseada em evidência (Fase Aguda, Intermediária e Avançada)
12. Protocolos em atletas (Progressão e Return to Play)
13. Algoritmo de decisão clínica
14. Red flags (Sinais de alerta urgente)
15. Evidência científica (Diretrizes e Recomendações)
"""

def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_paciente = types.InlineKeyboardButton("👤 Analisar Novo Paciente", callback_data="novo_paciente")
    btn_duvida = types.InlineKeyboardButton("📚 Dúvida Técnica Direta", callback_data="duvida_tecnica")
    markup.add(btn_paciente, btn_duvida)
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "🚀 **MestreFisio V4.2 Especialista**\nPronto para análise clínica profunda.", reply_markup=menu_principal())

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual a condição clínica para análise?")
        bot.register_next_step_handler(msg, processar_ia_direta)

def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: **{nome}**\nDescreva o quadro:")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):
    prompt = f"{PROMPT_SISTEMA}\n\nCASO: Paciente {nome}. {message.text}"
    chamar_gemini(message, prompt)

def processar_ia_direta(message):
    prompt = f"{PROMPT_SISTEMA}\n\nDÚVIDA/CONDIÇÃO: {message.text}"
    chamar_gemini(message, prompt)

def chamar_gemini(message, prompt):
    aguarde = bot.send_message(message.chat.id, "🧠 Estruturando raciocínio clínico (isso pode levar 30-40 segundos devido à profundidade da análise)...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    try:
        # Aumentamos o timeout para 120 segundos para suportar o prompt longo
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=120)
        analise = response.json()['candidates'][0]['content']['parts'][0]['text']
        bot.delete_message(message.chat.id, aguarde.message_id)
        
        # Divisão em blocos para o Telegram
        for i in range(0, len(analise), 4000):
            bot.send_message(message.chat.id, analise[i:i+4000], parse_mode="Markdown")
        
        bot.send_message(message.chat.id, "O que deseja fazer agora?", reply_markup=menu_principal())
    except:
        bot.send_message(message.chat.id, "⚠️ Ocorreu um erro de tempo. Tente ser mais específico no relato.")

if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    bot.infinity_polling()
