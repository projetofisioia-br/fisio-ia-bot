import telebot, requests, os, time
from telebot import types
from flask import Flask
from threading import Thread

# --- SERVIDOR WEB ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V5.0 - Global PhD Active"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
PAYMENT_TOKEN = os.environ.get("PAYMENT_TOKEN_TEST") # Configure no Render
MODELO = "gemini-2.5-flash"

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

# --- TRADUÇÕES E PROMPT ---
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
        'msg_ajuda': "⚖️ **AVISO LEGAL**\nFerramenta de auxílio. O diagnóstico final é de responsabilidade do profissional habilitado.",
        'pay_desc': "Acesso ilimitado a laudos e consultas PhD.",
        'sucesso': "✅ Pagamento confirmado! Acesso PhD Pro liberado!"
    },
    'en': {
        'start': "🚀 **MestreFisio PhD**\nHigh-performance system for deep clinical analysis.",
        'btn_paciente': "👤 New Patient",
        'btn_duvida': "📚 Technical Doubt",
        'btn_planos': "💎 Pro Access Plans",
        'btn_ajuda': "⚖️ Help & Legal Terms",
        'msg_ajuda': "⚖️ **LEGAL NOTICE**\nSupport tool only. Final diagnosis is the therapist's responsibility.",
        'pay_desc': "Unlimited access to PhD reports and consultations.",
        'sucesso': "✅ Payment confirmed! PhD Pro access activated!"
    }
}

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

# --- HANDLERS DE COMANDO ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    lang = obter_idioma(message)
    bot.send_message(message.chat.id, TEXTOS[lang]['start'], reply_markup=menu_principal(lang))

# --- LÓGICA DE PAGAMENTO GLOBAL ---
@bot.callback_query_handler(func=lambda call: call.data == "planos")
def enviar_fatura(call):
    lang = obter_idioma(call)
    moeda = "USD" if lang == 'en' else "BRL"
    preco = 1990 if lang == 'en' else 4990 # $19.90 ou R$ 49,90
    
    bot.send_invoice(
        call.message.chat.id,
        title="MestreFisio PhD Pro 💎",
        description=TEXTOS[lang]['pay_desc'],
        provider_token=PAYMENT_TOKEN,
        currency=moeda,
        prices=[types.LabeledPrice(label="PhD Pro", amount=preco)],
        start_parameter="mestre-fisio-pro",
        payload="pro_access_global"
    )

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout_confirm(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def pagamento_sucesso(m):
    lang = obter_idioma(m)
    # Aqui você pode adicionar a integração com seu MongoDB para salvar o status 'PRO'
    bot.send_message(m.chat.id, TEXTOS[lang]['sucesso'])

# --- LÓGICA CLÍNICA ORIGINAL (MANTIDA) ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    lang = obter_idioma(call)
    bot.answer_callback_query(call.id)
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente / Patient Name:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Qual condição deseja analisar? / What condition to analyze?")
        bot.register_next_step_handler(msg, processar_ia_direta)
    elif call.data == "ajuda_btn":
        bot.send_message(call.message.chat.id, TEXTOS[lang]['msg_ajuda'], parse_mode="Markdown")

def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    bot.send_message(message.chat.id, f"✅ Paciente: **{nome}**\nDescreva o quadro clínico:")
    bot.register_next_step_handler(message, processar_ia_paciente, nome)

def processar_ia_paciente(message, nome):
    prompt = f"{PROMPT_SISTEMA}\n\nAnalise detalhadamente o caso do paciente {nome}: {message.text}"
    chamar_gemini(message, prompt)

def processar_ia_direta(message):
    prompt = f"{PROMPT_SISTEMA}\n\nForneça uma explanação técnica PhD sobre: {message.text}"
    chamar_gemini(message, prompt)

def chamar_gemini(message, prompt):
    # Lógica de processamento em blocos e timeout de 400s mantida
    aguarde = bot.send_message(message.chat.id, "🧠 **Construindo raciocínio clínico...**")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=400)
        res_data = response.json()
        
        if 'candidates' in res_data:
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            bot.delete_message(message.chat.id, aguarde.message_id)
            
            partes = [analise[i:i+1500] for i in range(0, len(analise), 1500)]
            for p in partes:
                try:
                    bot.send_message(message.chat.id, p, parse_mode="Markdown")
                    time.sleep(1.2) 
                except:
                    bot.send_message(message.chat.id, p)
            
            bot.send_message(message.chat.id, "✅ **Análise Finalizada.**", reply_markup=menu_principal(obter_idioma(message)))
        else:
            bot.send_message(message.chat.id, "⚠️ Erro na estrutura da IA.")

    except Exception as e:
        bot.send_message(message.chat.id, "❌ Falha na conexão técnica.")

if __name__ == "__main__":
    Thread(target=run).start()
    bot.remove_webhook()
    time.sleep(2)
    bot.infinity_polling(timeout=120, long_polling_timeout=60)
