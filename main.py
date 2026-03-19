import telebot, requests, os, time, pymongo
from telebot import types
from flask import Flask
from threading import Thread
from datetime import datetime

# --- CONFIGURAÇÃO DO BANCO DE DADOS ---
MONGO_URI = os.environ.get("MONGO_URI")
client = pymongo.MongoClient(MONGO_URI)
db = client["MestreFisioDB"]
pacientes_coll = db["pacientes"]

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V5.1 - Memória e Segurança Ativa"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES DO BOT ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-2.5-flash"
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

PROMPT_SISTEMA = """
Você é um Fisioterapeuta PhD especializado em Traumato-Ortopedia.
Siga RIGOROSAMENTE a estrutura de 15 tópicos enviada anteriormente.
Seja técnico, profundo e baseie-se em evidências científicas.
"""

# --- FUNÇÕES DE BANCO DE DATA (Isolamento por User ID) ---
def salvar_no_historico(user_id, nome_paciente, texto_analise):
    data_atual = datetime.now().strftime("%d/%m/%Y %H:%M")
    # O filtro {"user_id": user_id} garante que cada fisio veja só seus pacientes
    pacientes_coll.update_one(
        {"user_id": user_id, "nome": nome_paciente.upper()},
        {"$push": {"consultas": {"data": data_atual, "relatorio": texto_analise}}},
        upsert=True
    )

def buscar_meus_pacientes(user_id):
    # Retorna a lista de nomes de todos os pacientes deste usuário
    cursor = pacientes_coll.find({"user_id": user_id}, {"nome": 1})
    return [p["nome"] for p in cursor]

# --- INTERFACE ---
def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👤 Novo Paciente / Analisar", callback_data="novo_paciente"),
        types.InlineKeyboardButton("📋 Meus Pacientes (Histórico)", callback_data="listar_pacientes"),
        types.InlineKeyboardButton("📚 Dúvida Técnica Direta", callback_data="duvida_tecnica")
    )
    return markup

@bot.message_handler(commands=['start'])
def welcome(message):
    bot.send_message(message.chat.id, "🚀 **MestreFisio V5.1 Ativado**\nMemória Cloud e Segurança de Dados OK.", reply_markup=menu_principal())

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Digite o NOME do paciente:")
        bot.register_next_step_handler(msg, iniciar_fluxo_paciente)
    
    elif call.data == "listar_pacientes":
        lista = buscar_meus_pacientes(user_id)
        if lista:
            resp = "📂 **Seus Pacientes Cadastrados:**\n\n" + "\n".join([f"• {n}" for n in lista])
            resp += "\n\n*Para ver o histórico, peça uma nova análise com o mesmo nome.*"
            bot.send_message(call.message.chat.id, resp)
        else:
            bot.send_message(call.message.chat.id, "📭 Ninguém cadastrado ainda.")

def iniciar_fluxo_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente **{nome}** identificado.\nDescreva o quadro clínico:")
    bot.register_next_step_handler(msg, processar_ia, nome)

def processar_ia(message, nome):
    user_id = message.from_user.id
    aguarde = bot.send_message(message.chat.id, "🧠 **Gerando Relatório PhD e Salvando na Nuvem...**")
    
    prompt = f"{PROMPT_SISTEMA}\n\nAnalise: Paciente {nome}. {message.text}"
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=300)
        analise = response.json()['candidates'][0]['content']['parts'][0]['text']
        
        # SALVAMENTO PERSISTENTE
        salvar_no_historico(user_id, nome, analise)
        
        bot.delete_message(message.chat.id, aguarde.message_id)
        
        # ENVIO FRACIONADO (Estabilidade V4.7)
        for i in range(0, len(analise), 2000):
            bot.send_message(message.chat.id, analise[i:i+2000], parse_mode="Markdown")
            time.sleep(1)
            
        bot.send_message(message.chat.id, "✅ Relatório concluído e arquivado.", reply_markup=menu_principal())
        
    except Exception as e:
        bot.send_message(message.chat.id, "❌ Erro no processamento. Verifique sua chave de IA ou conexão.")

if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    time.sleep(2)
    bot.infinity_polling(timeout=90, long_polling_timeout=30)
