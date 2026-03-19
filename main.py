import telebot, requests, os, time, pymongo
from telebot import types
from flask import Flask
from threading import Thread
from datetime import datetime

# --- 1. CONFIGURAÇÃO DO BANCO DE DADOS ---
MONGO_URI = os.environ.get("MONGO_URI")
client = pymongo.MongoClient(MONGO_URI)
db = client["MestreFisioDB"]
pacientes_coll = db["pacientes"]

# --- 2. SERVIDOR WEB (KEEP ALIVE) ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V5.2 - Gestão de Dados Ativa"

def run(): app.run(host='0.0.0.0', port=10000)

# --- 3. CONFIGURAÇÕES DO BOT ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-2.5-flash"
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

PROMPT_SISTEMA = """
Você é um Fisioterapeuta PhD especializado em Traumato-Ortopedia.
Siga RIGOROSAMENTE a estrutura de 15 tópicos enviada anteriormente.
Seja técnico, profundo e baseie-se em evidências científicas.
"""

# --- 4. FUNÇÕES DE BANCO DE DADOS (Lógica de Negócio) ---
def salvar_no_historico(user_id, nome_paciente, texto_analise):
    data_atual = datetime.now().strftime("%d/%m/%Y %H:%M")
    pacientes_coll.update_one(
        {"user_id": user_id, "nome": nome_paciente.upper()},
        {"$push": {"consultas": {"data": data_atual, "relatorio": texto_analise}}},
        upsert=True
    )

def buscar_meus_pacientes(user_id):
    cursor = pacientes_coll.find({"user_id": user_id}, {"nome": 1})
    return [p["nome"] for p in cursor]

def excluir_paciente_db(user_id, nome_paciente):
    resultado = pacientes_coll.delete_one({"user_id": user_id, "nome": nome_paciente.upper()})
    return resultado.deleted_count > 0

# --- 5. INTERFACE E MENUS ---
def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👤 Novo Paciente / Analisar", callback_data="novo_paciente"),
        types.InlineKeyboardButton("📋 Meus Pacientes (Histórico)", callback_data="listar_pacientes"),
        types.InlineKeyboardButton("🗑️ Excluir Paciente", callback_data="deletar_paciente"),
        types.InlineKeyboardButton("📚 Dúvida Técnica Direta", callback_data="duvida_tecnica")
    )
    return markup

@bot.message_handler(commands=['start'])
def welcome(message):
    bot.send_message(message.chat.id, "🚀 **MestreFisio V5.2**\nGestão de pacientes e nuvem conectada.", reply_markup=menu_principal())

# --- 6. HANDLERS DE CALLBACK (Botões) ---
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
            bot.send_message(call.message.chat.id, resp, reply_markup=menu_principal())
        else:
            bot.send_message(call.message.chat.id, "📭 Ninguém cadastrado ainda.", reply_markup=menu_principal())

    elif call.data == "deletar_paciente":
        msg = bot.send_message(call.message.chat.id, "🗑️ Digite o NOME EXATO do paciente para excluir:")
        bot.register_next_step_handler(msg, confirmar_exclusao)

# --- 7. LÓGICA DE PROCESSAMENTO ---
def confirmar_exclusao(message):
    nome = message.text.upper().strip()
    user_id = message.from_user.id
    if excluir_paciente_db(user_id, nome):
        bot.send_message(message.chat.id, f"✅ Histórico de **{nome}** apagado.", reply_markup=menu_principal())
    else:
        bot.send_message(message.chat.id, "❌ Paciente não encontrado.", reply_markup=menu_principal())

def iniciar_fluxo_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente **{nome}** identificado.\nDescreva o quadro clínico:")
    bot.register_next_step_handler(msg, processar_ia, nome)

def processar_ia(message, nome):
    user_id = message.from_user.id
    aguarde = bot.send_message(message.chat.id, "🧠 **Gerando Relatório PhD e Salvando...**")
    prompt = f"{PROMPT_SISTEMA}\n\nAnalise: Paciente {nome}. {message.text}"
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=300)
        analise = response.json()['candidates'][0]['content']['parts'][0]['text']
        
        salvar_no_historico(user_id, nome, analise)
        bot.delete_message(message.chat.id, aguarde.message_id)
        
        for i in range(0, len(analise), 2000):
            bot.send_message(message.chat.id, analise[i:i+2000], parse_mode="Markdown")
            time.sleep(1)
            
        bot.send_message(message.chat.id, "✅ Relatório arquivado.", reply_markup=menu_principal())
    except:
        bot.send_message(message.chat.id, "❌ Erro. Tente novamente.")

# --- 8. INICIALIZAÇÃO ---
if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    time.sleep(2)
    bot.infinity_polling(timeout=90, long_polling_timeout=30)
