import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V5.5 - Online"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM").strip()
API_KEY_IA = os.environ.get("API_KEY_IA")
PAYMENT_TOKEN_TEST = str(os.environ.get("PAYMENT_TOKEN_TEST", "")).strip()
MONGO_URI = os.environ.get("MONGO_URI")
MODELO = "gemini-1.5-flash"

client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
usuarios_coll = db['usuarios']

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# --- PROMPT E TRADUÇÕES ---
PROMPT_SISTEMA = "Atue como um Fisioterapeuta PhD. Forneça uma análise técnica estruturada em 15 tópicos..."

TEXTOS = {
    'pt': {
        'start': "🚀 **MestreFisio PhD**\nSistema de alta performance para análises clínicas profundas.",
        'pay_desc': "Assinatura Pro: Acesso ilimitado a laudos e consultas PhD.",
        'bloqueio': "⚠️ **Limite de Teste Atingido!**\n\nSuas 3 consultas gratuitas acabaram. Para continuar oferecendo tratamentos assertivos e diferenciados, assine o plano Pro.",
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
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👤 Novo Paciente", callback_data="novo_paciente"),
        types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida_tecnica"),
        types.InlineKeyboardButton("💎 Planos de Acesso Pro", callback_data="planos"),
        types.InlineKeyboardButton("⚖️ Ajuda e Termos", callback_data="ajuda_btn")
    )
    return markup

# --- 1. HANDLERS DE PAGAMENTO (PRIORIDADE TOTAL) ---

@bot.callback_query_handler(func=lambda call: call.data == "planos")
def enviar_fatura(call):
    lang = obter_idioma(call)
    moeda = "USD" if lang == 'en' else "BRL"
    preco = 1990 if lang == 'en' else 5990
    
    try:
        bot.send_invoice(
            call.message.chat.id,
            title="MestreFisio PhD Pro 💎",
            description=TEXTOS[lang]['pay_desc'],
            provider_token=PAYMENT_TOKEN,
            currency=moeda,
            prices=[types.LabeledPrice(label="Assinatura Mensal", amount=preco)],
            start_parameter="mestre-fisio-pro",
            payload="pro_access_global"
        )
        bot.answer_callback_query(call.id)
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Erro no Provedor: Verifique o TOKEN_PAYMENT no Render.")

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
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual condição deseja analisar?")
        bot.register_next_step_handler(msg, processar_ia_direta)
    elif call.data == "ajuda_btn":
        bot.send_message(call.message.chat.id, "⚖️ Aviso Legal: Ferramenta de auxílio profissional.")
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

    aguarde = bot.send_message(message.chat.id, "🧠 **Construindo raciocínio clínico...**")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    try:
        # Context Caching nativo: o prompt de sistema é fixo e otimizado pelo modelo 1.5
        payload = {"contents": [{"parts": [{"text": f"{PROMPT_SISTEMA}\n\n{prompt}"}]}]}
        response = requests.post(url, json=payload, timeout=400)
        res_data = response.json()
        
        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            usuarios_coll.update_one({"user_id": user_id}, {"$inc": {"consultas": 1}}, upsert=True)
            bot.delete_message(message.chat.id, aguarde.message_id)
            for parte in [analise[i:i+1500] for i in range(0, len(analise), 1500)]:
                bot.send_message(message.chat.id, parte, parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, "⚠️ IA indisponível. Tente em instantes.")
    except:
        bot.send_message(message.chat.id, "❌ Falha de conexão.")

# --- 4. FUNÇÕES DE FLUXO ---
def obter_nome_paciente(m):
    nome = m.text.upper().strip()
    msg = bot.send_message(m.chat.id, f"✅ Paciente: **{nome}**\nDescreva o quadro:")
    bot.register_next_step_handler(msg, lambda msg: chamar_gemini(msg, f"Paciente {nome}: {msg.text}"))

def processar_ia_direta(m):
    chamar_gemini(m, f"Explanação técnica sobre: {m.text}")

@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, TEXTOS[obter_idioma(m)]['start'], reply_markup=menu_principal(obter_idioma(m)))

if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    bot.infinity_polling(timeout=120)
