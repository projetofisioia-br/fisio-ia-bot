import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V8.0 - Estabilidade Total Ativa"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MONGO_URI = os.environ.get("MONGO_URI")
TOKEN_PAYMENT = os.environ.get("TOKEN_PAYMENT")
MODELO = "gemini-1.5-flash" # Mantido conforme sua base funcional

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# Conexão com Banco de Dados para Histórico
client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
usuarios_coll = db['usuarios']
pacientes_coll = db['pacientes']

PROMPT_SISTEMA = """
Atue como um Fisioterapeuta PhD. Forneça uma análise técnica estruturada em 15 tópicos obrigatórios (Definição, Anatomia/Biomecânica, Etiologia, Sintomas, Raciocínio, Avaliação, Testes, Diagnóstico Diferencial, Exames, Classificação, Conduta, Protocolo Atleta, Algoritmo, Red Flags e Evidências). 
Use linguagem científica de alto nível e formatação Markdown clara.
"""

# --- MENUS ATUALIZADOS ---
def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👤 Novo Paciente", callback_data="novo_paciente"),
        types.InlineKeyboardButton("📂 Histórico de Pacientes", callback_data="ver_historico"),
        types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica"),
        types.InlineKeyboardButton("💎 Planos de Acesso Pro", callback_data="planos")
    )
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "🚀 **MestreFisio V8.0 Especialista**\nSistema de alta performance para análises profundas.", reply_markup=menu_principal())

# --- TRATAMENTO DE CLIQUES ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id

    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
    
    elif call.data == "ver_historico":
        pacientes = list(pacientes_coll.find({"profissional_id": user_id}))
        if not pacientes:
            bot.send_message(call.message.chat.id, "📭 Você ainda não tem pacientes salvos.")
        else:
            txt = "📂 **Seus Pacientes Cadastrados:**\n\n"
            for p in pacientes:
                txt += f"• **{p['nome']}** - {p['data']}\n"
            bot.send_message(call.message.chat.id, txt, parse_mode="Markdown")
            
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual condição deseja analisar hoje?")
        bot.register_next_step_handler(msg, processar_ia_direta)
        
    elif call.data == "planos":
        bot.send_invoice(
            call.message.chat.id, 
            title="MestreFisio PhD Pro 💎", 
            description="Acesso ilimitado às análises clínicas.",
            provider_token=TOKEN_PAYMENT,
            currency="BRL",
            prices=[types.LabeledPrice("Assinatura Pro", 5990)],
            invoice_payload="pro_access",
            start_parameter="pro_access"
        )

# --- FUNÇÕES DE CAPTURA ---
def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: **{nome}**\nDescreva o quadro clínico para análise:")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):
    prompt = f"{PROMPT_SISTEMA}\n\nAnalise detalhadamente o caso do paciente {nome}: {message.text}"
    chamar_gemini(message, prompt, nome)

def processar_ia_direta(message):
    prompt = f"{PROMPT_SISTEMA}\n\nForneça uma explanação técnica PhD sobre: {message.text}"
    chamar_gemini(message, prompt)

# --- CORE DA IA (MANTIDO IDÊNTICO À SUA BASE FUNCIONAL) ---
def chamar_gemini(message, prompt, nome_paciente=None):
    user_id = message.from_user.id
    # Verificação de Limite Simples
    user_data = usuarios_coll.find_one({"user_id": user_id}) or {"plano": "FREE", "consultas": 0}
    if user_data.get("plano") != "PRO" and user_data.get("consultas", 0) >= 3:
        bot.send_message(message.chat.id, "⚠️ Limite Free atingido. Assine o Pro para continuar.", reply_markup=menu_principal())
        return

    aguarde = bot.send_message(message.chat.id, "🧠 **Construindo raciocínio clínico...**")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=400)
        res_data = response.json()
        
        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            bot.delete_message(message.chat.id, aguarde.message_id)
            
            # SALVAR NO HISTÓRICO
            if nome_paciente:
                pacientes_coll.update_one(
                    {"profissional_id": user_id, "nome": nome_paciente},
                    {"$set": {"ultima_analise": analise, "data": time.strftime("%d/%m/%Y")}},
                    upsert=True
                )
            
            # Incrementar contador
            usuarios_coll.update_one({"user_id": user_id}, {"$inc": {"consultas": 1}}, upsert=True)

            # DIVISÃO EM MICRO-BLOCOS (Mantido para estabilidade)
            partes = [analise[i:i+1500] for i in range(0, len(analise), 1500)]
            for p in partes:
                try:
                    bot.send_message(message.chat.id, p, parse_mode="Markdown")
                    time.sleep(1.2) 
                except:
                    bot.send_message(message.chat.id, p)
            
            bot.send_message(message.chat.id, "✅ **Análise Finalizada.**", reply_markup=menu_principal())
        else:
            bot.send_message(message.chat.id, "⚠️ Erro na IA. Verifique se o prompt não viola as políticas do Google.")

    except Exception as e:
        bot.send_message(message.chat.id, "❌ Falha na conexão técnica.")

if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    time.sleep(2)
    bot.infinity_polling(timeout=120, long_polling_timeout=60)
