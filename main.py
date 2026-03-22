import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient # INSERIDO: Biblioteca do Histórico

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V4.7 - Estabilidade de Fluxo PhD Ativa"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-1.5-flash" # AJUSTADO: Versão estável para evitar Erro 404
MONGO_URI = os.environ.get("MONGO_URI") # INSERIDO: Conexão Histórico
TOKEN_PAYMENT = os.environ.get("TOKEN_PAYMENT") # INSERIDO: Conexão Pagamento

# INSERIDO: Inicialização do Banco de Dados
client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
usuarios_coll = db['usuarios']
pacientes_coll = db['pacientes']

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

PROMPT_SISTEMA = """
Atue como um Fisioterapeuta PhD. Forneça uma análise técnica estruturada em 15 tópicos obrigatórios (Definição, Anatomia/Biomecânica, Etiologia, Sintomas, Raciocínio, Avaliação, Testes, Diagnóstico Diferencial, Exames, Classificação, Conduta, Protocolo Atleta, Algoritmo, Red Flags e Evidências). 
Use linguagem científica de alto nível e formatação Markdown clara.
"""

# INSERIDO: Menu com Histórico e Planos
def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_paciente = types.InlineKeyboardButton("👤 Novo Paciente", callback_data="novo_paciente")
    btn_historico = types.InlineKeyboardButton("📂 Histórico de Pacientes", callback_data="ver_historico")
    btn_duvida = types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica")
    btn_planos = types.InlineKeyboardButton("💎 Planos de Acesso Pro", callback_data="planos")
    markup.add(btn_paciente, btn_historico, btn_duvida, btn_planos)
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "🚀 **MestreFisio V4.7 Especialista**\nSistema de alta performance para análises profundas.", reply_markup=menu_principal())

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual condição deseja analisar hoje?")
        bot.register_next_step_handler(msg, processar_ia_direta)
    # INSERIDO: Lógica de Histórico e Pagamento
    elif call.data == "ver_historico":
        pacientes = list(pacientes_coll.find({"profissional_id": call.from_user.id}))
        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Histórico vazio.")
        else:
            txt = "📂 **Seus Pacientes:**\n" + "\n".join([f"• {p['nome']} ({p['data']})" for p in pacientes])
            bot.send_message(call.message.chat.id, txt)
    elif call.data == "planos":
        bot.send_invoice(
            call.message.chat.id, "MestreFisio PhD Pro 💎", "Acesso ilimitado.",
            TOKEN_PAYMENT, "BRL", [types.LabeledPrice("Pro", 5990)],
            invoice_payload="pro_access", start_parameter="pro"
        )

def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: **{nome}**\nDescreva o quadro clínico para análise:")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):
    prompt = f"{PROMPT_SISTEMA}\n\nAnalise detalhadamente o caso do paciente {nome}: {message.text}"
    chamar_gemini(message, prompt, nome) # AJUSTADO: Passa o nome

def processar_ia_direta(message):
    prompt = f"{PROMPT_SISTEMA}\n\nForneça uma explanação técnica PhD sobre: {message.text}"
    chamar_gemini(message, prompt)

def chamar_gemini(message, prompt, nome_paciente=None):
    aguarde = bot.send_message(message.chat.id, "🧠 **Construindo raciocínio clínico...**")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    # INSERIDO: Filtros de segurança para evitar erro de "Política do Google"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }

    try:
        response = requests.post(url, json=payload, timeout=400)
        res_data = response.json()
        
        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            
            # INSERIDO: Gravação no Histórico
            if nome_paciente:
                pacientes_coll.update_one(
                    {"profissional_id": message.from_user.id, "nome": nome_paciente},
                    {"$set": {"ultima_analise": analise, "data": time.strftime("%d/%m/%Y")}},
                    upsert=True
                )

            bot.delete_message(message.chat.id, aguarde.message_id)
            partes = [analise[i:i+1500] for i in range(0, len(analise), 1500)]
            for p in partes:
                try:
                    bot.send_message(message.chat.id, p, parse_mode="Markdown")
                    time.sleep(1.2) 
                except:
                    bot.send_message(message.chat.id, p)
            bot.send_message(message.chat.id, "✅ **Análise Finalizada.**", reply_markup=menu_principal())
        else:
            bot.send_message(message.chat.id, "⚠️ Erro na IA. Tente reformular.")

    except Exception as e:
        bot.send_message(message.chat.id, "❌ Falha na conexão técnica.")

if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    time.sleep(2)
    bot.infinity_polling(timeout=120, long_polling_timeout=60)
