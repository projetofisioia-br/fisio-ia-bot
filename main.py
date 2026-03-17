import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): 
    return "MestreFisio V4.1 - PROMPT ULTRA-AVANÇADO ATIVO"

def run():
    app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-2.5-flash"

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=True)

# --- DEFINIÇÃO DO PROMPT MESTRE ---
# Aqui inserimos a sua nova diretriz ultra-especializada
PROMPT_SISTEMA = """
Você é um assistente clínico altamente especializado em fisioterapia musculoesquelética, ortopedia e medicina esportiva. 
Seu papel é auxiliar profissionais da saúde no raciocínio diagnóstico baseado em evidências.

ESTRUTURA OBRIGATÓRIA DA RESPOSTA:
1. Definição clínica (Conceito, anatomia, fisiopatologia).
2. Anatomia e biomecânica envolvida.
3. Etiologia / causas (Categorize em Traumática, Degenerativa, Sobrecarga, etc).
4. Sinais e sintomas (Dor, irradiação, limitações).
5. Raciocínio clínico inicial.
6. Avaliação clínica passo a passo (Anamnese, Inspeção, Palpação, Funcional).
7. Testes clínicos ortopédicos (Nome, objetivo, técnica, positivo, interpretação).
8. Diagnósticos diferenciais.
9. Exames complementares (Quando pedir cada um).
10. Classificação da lesão (Graus/Critérios).
11. Conduta fisioterapêutica (Fases: Aguda, Intermediária, Avançada).
12. Protocolos em atletas (Progressão de carga e Return to Play).
13. Algoritmo de decisão clínica.
14. Red flags (Sinais de alerta urgente).
15. Evidência científica (Diretrizes e estudos).

Use subtítulos claros, listas organizadas e linguagem técnica de nível pós-graduação.
"""

def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_paciente = types.InlineKeyboardButton("👤 Analisar Novo Paciente", callback_data="novo_paciente")
    btn_duvida = types.InlineKeyboardButton("📚 Dúvida Técnica Direta", callback_data="duvida_tecnica")
    markup.add(btn_paciente, btn_duvida)
    return markup

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.send_message(message.chat.id, "🚀 **MestreFisio V4.1 Especialista**\nSistema de raciocínio clínico avançado ativado.", reply_markup=menu_principal(), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Digite o **NOME** do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Digite sua dúvida clínica:")
        bot.register_next_step_handler(msg, processar_ia_direta)

def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: **{nome}**\nDescreva o quadro clínico completo:")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):
    # Combinamos o Prompt de Sistema com o caso específico
    prompt_final = f"{PROMPT_SISTEMA}\n\nCASO CLÍNICO DO PACIENTE {nome}:\n{message.text}"
    chamar_gemini(message, prompt_final)

def processar_ia_direta(message):
    prompt_final = f"{PROMPT_SISTEMA}\n\nDÚVIDA TÉCNICA:\n{message.text}"
    chamar_gemini(message, prompt_final)

def chamar_gemini(message, prompt):
    aguarde = bot.send_message(message.chat.id, "🧠 Estruturando raciocínio clínico avançado...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=90)
        analise = response.json()['candidates'][0]['content']['parts'][0]['text']
        bot.delete_message(message.chat.id, aguarde.message_id)
        
        # O Telegram corta mensagens acima de 4096 caracteres. 
        # Como o novo prompt é profundo, o bot agora divide a resposta automaticamente em blocos.
        if len(analise) > 4000:
            partes = [analise[i:i+4000] for i in range(0, len(analise), 4000)]
            for p in partes:
                bot.send_message(message.chat.id, p, parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, analise, parse_mode="Markdown")
        
        bot.send_message(message.chat.id, "Deseja aprofundar em algum ponto?", reply_markup=menu_principal())
            
    except Exception as e:
        bot.send_message(message.chat.id, "❌ Erro ao processar. Tente simplificar o relato ou reenviar.")

if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    time.sleep(1)
    bot.infinity_polling()
