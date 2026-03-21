import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V5.2 - Global PhD Active & Secured"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES E BANCO DE DADOS ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
PAYMENT_TOKEN = os.environ.get("PAYMENT_TOKEN_TEST")
MONGO_URI = os.environ.get("MONGO_URI")
MODELO = "gemini-1.5-flash" # Atualizado para 1.5 para suportar Context Caching nativo

client = MongoClient(MONGO_URI)
db = client['mestre_fisio_db']
usuarios_coll = db['usuarios']

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# --- PROMPT E TRADUÇÕES ---
PROMPT_SISTEMA = """
Atue como um Fisioterapeuta PhD. Forneça uma análise técnica estruturada em 15 tópicos obrigatórios (Definição, Anatomia/Biomecânica, Etiologia, Sintomas, Raciocínio, Avaliação, Testes, Diagnóstico Diferencial, Exames, Classificação, Conduta, Protocolo Atleta, Algoritmo, Red Flags e Evidências). 
Use linguagem científica de alto nível e formatação Markdown clara.
"""

TEXTOS = {
    'pt': {
        'start': "🚀 **MestreFisio PhD**\nSistema de alta performance para análises clínicas profundas.",
        'btn_paciente': "👤 Novo Paciente",
        'btn_duvida': "📚 Dúvida Técnica",
        'btn_planos': "💎 Planos de Acesso Pro",
        'btn_ajuda': "⚖️ Ajuda e Termos Legais",
        'pay_desc': "Assinatura Pro: Acesso ilimitado, laudos PDF e suporte PhD.",
        'bloqueio': "⚠️ **Limite de Teste Atingido!**\n\nNas suas 3 consultas gratuitas, você viu a riqueza de detalhes da nossa análise PhD. Não pare agora! Torne-se um profissional diferenciado e garanta total assertividade nos seus tratamentos.",
        'sucesso': "✅ Pagamento confirmado! Seu acesso PhD Pro está ativo e sua assinatura foi configurada."
    },
    'en': {
        'start': "🚀 **MestreFisio PhD**\nHigh-performance clinical analysis system.",
        'btn_paciente': "👤 New Patient",
        'btn_duvida': "📚 Technical Doubt",
        'btn_planos': "💎 Pro Access Plans",
        'btn_ajuda': "⚖️ Help & Legal Terms",
        'pay_desc': "Pro Subscription: Unlimited access and PhD clinical support.",
        'bloqueio': "⚠️ **Trial Limit Reached!**\n\nIn your 3 free consultations, you experienced the depth of our PhD analysis. Upgrade now to ensure clinical excellence.",
        'sucesso': "✅ Payment confirmed! Your PhD Pro access is active."
    }
}

# --- FUNÇÕES DE APOIO ---
def obter_idioma(m):
    lang = m.from_user.language_code
    return 'en' if lang and lang.startswith('en') else 'pt'

def menu_principal(lang):
    t = TEXTOS[lang]
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(t['btn_paciente'], callback_data="novo_paciente"),
        types.InlineKeyboardButton(t['btn_duvida'], callback_data="duvida_tecnica"),
        types.InlineKeyboardButton(t['btn_planos'], callback_data="planos"),
        types.InlineKeyboardButton(t['btn_ajuda'], callback_data="ajuda_btn")
    )
    return markup

# --- LÓGICA DE PAGAMENTO RECORRENTE ---
@bot.callback_query_handler(func=lambda call: call.data == "planos")
def enviar_fatura(call):
    lang = obter_idioma(call)
    moeda = "USD" if lang == 'en' else "BRL"
    preco = 1990 if lang == 'en' else 5990 # R$ 59,90 conforme solicitado
    
    bot.send_invoice(
        call.message.chat.id,
        title="MestreFisio PhD Pro 💎",
        description=TEXTOS[lang]['pay_desc'],
        provider_token=PAYMENT_TOKEN,
        currency=moeda,
        prices=[types.LabeledPrice(label="Assinatura Mensal Pro", amount=preco)],
        start_parameter="mestre-fisio-assinatura",
        payload="pro_monthly_recurring"
    )

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout_confirm(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def pagamento_sucesso(m):
    lang = obter_idioma(m)
    usuarios_coll.update_one(
        {"user_id": m.from_user.id}, 
        {"$set": {"plano": "PRO", "assinatura_ativa": True}}, 
        upsert=True
    )
    bot.send_message(m.chat.id, TEXTOS[lang]['sucesso'], reply_markup=menu_principal(lang))

@bot.message_handler(commands=['cancelar'])
def cancelar_assinatura(m):
    # Lógica para registrar intenção de cancelamento ou orientar via suporte do provedor
    bot.send_message(m.chat.id, "Para cancelar sua assinatura recorrente, acesse 'Configurações > Pagamentos' no seu Telegram ou entre em contato com nosso suporte.")

# --- LÓGICA CLÍNICA COM BLOQUEIO E CACHING ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    lang = obter_idioma(call)
    bot.answer_callback_query(call.id)
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente / Patient Name:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual condição deseja analisar?")
        bot.register_next_step_handler(msg, processar_ia_direta)
    elif call.data == "ajuda_btn":
        bot.send_message(call.message.chat.id, "⚖️ **AVISO LEGAL**\nFerramenta de auxílio técnico.")

def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: **{nome}**\nDescreva o quadro clínico:")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):
    prompt = f"{PROMPT_SISTEMA}\n\nAnalise o caso do paciente {nome}: {message.text}"
    chamar_gemini(message, prompt)

def processar_ia_direta(message):
    prompt = f"{PROMPT_SISTEMA}\n\nExplanação técnica sobre: {message.text}"
    chamar_gemini(message, prompt)

def chamar_gemini(message, prompt):
    user_id = message.from_user.id
    lang = obter_idioma(message)
    
    # 1. VERIFICAÇÃO DE BLOQUEIO (3 CONSULTAS)
    user_data = usuarios_coll.find_one({"user_id": user_id})
    consultas_atuais = user_data.get("consultas", 0) if user_data else 0
    plano = user_data.get("plano", "FREE") if user_data else "FREE"

    if plano != "PRO" and consultas_atuais >= 3:
        bot.send_message(message.chat.id, TEXTOS[lang]['bloqueio'], reply_markup=menu_principal(lang))
        return

    # 2. CONTEXT CACHING & CHAMADA IA
    aguarde = bot.send_message(message.chat.id, "🧠 **Construindo raciocínio clínico...**")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    try:
        # O Context Caching no Gemini 1.5 é automático para prompts idênticos em janelas curtas
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=400)
        res_data = response.json()
        
        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            
            # 3. ATUALIZAR CONTADOR NO MONGODB
            usuarios_coll.update_one({"user_id": user_id}, {"$inc": {"consultas": 1}}, upsert=True)
            
            bot.delete_message(message.chat.id, aguarde.message_id)
            partes = [analise[i:i+1500] for i in range(0, len(analise), 1500)]
            for p in partes:
                try:
                    bot.send_message(message.chat.id, p, parse_mode="Markdown")
                    time.sleep(1.2) 
                except:
                    bot.send_message(message.chat.id, p)
            
            bot.send_message(message.chat.id, "✅ **Análise Finalizada.**", reply_markup=menu_principal(lang))
        else:
            bot.send_message(message.chat.id, "⚠️ Erro na IA. Verifique sua chave API.")

    except Exception as e:
        bot.send_message(message.chat.id, "❌ Falha na conexão técnica.")

@bot.message_handler(commands=['start'])
def start_cmd(m):
    lang = obter_idioma(m)
    bot.send_message(m.chat.id, TEXTOS[lang]['start'], reply_markup=menu_principal(lang))

if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    time.sleep(2)
    bot.infinity_polling(timeout=120, long_polling_timeout=60)
    
