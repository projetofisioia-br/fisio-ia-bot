import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V5.3 - Pagamentos Corrigidos"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES E BANCO DE DADOS ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
PAYMENT_TOKEN = os.environ.get("PAYMENT_TOKEN_TEST") # Certifique-se que o token TEST: está aqui
MONGO_URI = os.environ.get("MONGO_URI")
MODELO = "gemini-1.5-flash"

client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
usuarios_coll = db['usuarios']

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# --- PROMPT E TEXTOS ---
PROMPT_SISTEMA = "Atue como um Fisioterapeuta PhD. Forneça uma análise técnica estruturada em 15 tópicos..."

TEXTOS = {
    'pt': {
        'start': "🚀 **MestreFisio PhD**\nSistema de alta performance para análises clínicas.",
        'pay_desc': "Assinatura Pro: Acesso ilimitado e suporte PhD.",
        'bloqueio': "⚠️ **Limite de Teste Atingido!**\nSua experiência clínica merece o nível PhD. Assine o Pro para continuar.",
        'sucesso': "✅ Pagamento confirmado! Acesso PhD Pro liberado!"
    },
    'en': {
        'start': "🚀 **MestreFisio PhD**\nHigh-performance clinical analysis system.",
        'pay_desc': "Pro Subscription: Unlimited access.",
        'bloqueio': "⚠️ **Trial Limit Reached!** Upgrade to Pro for unlimited access.",
        'sucesso': "✅ Payment confirmed! Pro access activated!"
    }
}

def obter_idioma(m):
    lang = m.from_user.language_code
    return 'en' if lang and lang.startswith('en') else 'pt'

def menu_principal(lang):
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(
        types.InlineKeyboardButton("👤 Novo Paciente", callback_data="novo_paciente"),
        types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica"),
        types.InlineKeyboardButton("💎 Planos de Acesso Pro", callback_data="planos"),
        types.InlineKeyboardButton("⚖️ Ajuda e Termos", callback_data="ajuda_btn")
    )
    return m

# --- 1. HANDLERS DE PAGAMENTO (PRECISAM VIR PRIMEIRO) ---

@bot.callback_query_handler(func=lambda call: call.data == "planos")
def enviar_fatura(call):
    lang = obter_idioma(call)
    moeda = "USD" if lang == 'en' else "BRL"
    preco = 1990 if lang == 'en' else 5990 # R$ 59,90
    
    try:
        bot.send_invoice(
            call.message.chat.id,
            title="MestreFisio PhD Pro 💎",
            description=TEXTOS[lang]['pay_desc'],
            provider_token=PAYMENT_TOKEN,
            currency=moeda,
            prices=[types.LabeledPrice(label="Assinatura Pro", amount=preco)],
            start_parameter="mestre-fisio-pro",
            payload="pro_access_global"
        )
        bot.answer_callback_query(call.id)
    except Exception as e:
        bot.send_message(call.message.chat.id, "❌ Erro ao gerar fatura. Verifique o Token de Pagamento no Render.")

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout_confirm(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def pagamento_sucesso(m):
    usuarios_coll.update_one({"user_id": m.from_user.id}, {"$set": {"plano": "PRO"}}, upsert=True)
    bot.send_message(m.chat.id, TEXTOS[obter_idioma(m)]['sucesso'])

# --- 2. OUTROS CALLBACKS ---

@bot.callback_query_handler(func=lambda call: True)
def callback_geral(call):
    lang = obter_idioma(call)
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual condição deseja analisar?")
        bot.register_next_step_handler(msg, processar_ia_direta)
    elif call.data == "ajuda_btn":
        bot.send_message(call.message.chat.id, "⚖️ Aviso Legal: Uso profissional apenas.")
    bot.answer_callback_query(call.id)

# --- 3. LÓGICA IA COM BLOQUEIO E CACHING ---

def chamar_gemini(message, prompt):
    user_id = message.from_user.id
    user_data = usuarios_coll.find_one({"user_id": user_id})
    consultas = user_data.get("consultas", 0) if user_data else 0
    plano = user_data.get("plano", "FREE") if user_data else "FREE"

    if plano != "PRO" and consultas >= 3:
        bot.send_message(message.chat.id, TEXTOS[obter_idioma(message)]['bloqueio'], reply_markup=menu_principal(obter_idioma(message)))
        return

    aguarde = bot.send_message(message.chat.id, "🧠 **Processando com Context Caching...**")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=400)
        res_data = response.json()
        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            usuarios_coll.update_one({"user_id": user_id}, {"$inc": {"consultas": 1}}, upsert=True)
            bot.delete_message(message.chat.id, aguarde.message_id)
            for parte in [analise[i:i+1500] for i in range(0, len(analise), 1500)]:
                bot.send_message(message.chat.id, parte, parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, "⚠️ Erro na IA.")
    except:
        bot.send_message(message.chat.id, "❌ Falha de conexão.")

# (Manter funções obter_nome_paciente, processar_ia_paciente, processar_ia_direta e main)
